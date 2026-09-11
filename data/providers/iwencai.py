"""Iwencai specialist provider."""
from __future__ import annotations

import re
import time
from typing import Any

from .errors import ProviderUnavailable
from .legacy import RunnerProvider, iw_runner
from .models import DataResult

_QFQ_KEY = re.compile(r"收盘价_前复权\[(\d{8})\]")   # 只取收盘价，避免开盘/最高/最低撞键
_CLOSE_KEY = re.compile(r"^收盘价\[(\d{8})\]$")      # 不复权收盘（指数用）
_DATE_KEY = re.compile(r"\[(\d{8})\]")

# 宽行查询（pattern_history 与 signal_score 回填共用同一形状）
_WIDE_FIELDS = ("交易日期 开盘价 收盘价 最高价 最低价 前复权开盘价 前复权收盘价 "
                "前复权最高价 前复权最低价 成交量 换手率")


def _row_dates(row: dict) -> list[str]:
    return sorted({m.group(1) for k in row for m in [_DATE_KEY.search(str(k))] if m})


def _first_row(resp: Any) -> dict:
    if isinstance(resp, dict) and resp.get("success") and resp.get("datas"):
        first = resp["datas"][0]
        if isinstance(first, dict):
            return first
    return {}


def query_wide_row(target: str, days: int, min_rows: int = 0,
                   fields: str = _WIDE_FIELDS) -> dict:
    """宽行查询；**低于调用方下限**即绕缓存重试一次，取日期更多的整段结果。

    🆕 v7.3.4 复审修复（第 3 项）：旧实现只在**日期数为 0** 时重试——问财偶发
    瞬时降级（500 日查询只回寥寥几日，2026-07-29 实测）返回 1~几十日时不重试，
    残缺序列被当作完整历史。现由调用方给出下限（pattern=最长窗口+20、回填=覆盖
    目标窗口所需），低于下限就重试一次并选日期更多的结果；仍为空才抛
    :class:`ProviderUnavailable`（上层 fail-closed）。
    """
    from iwencai_api import query_iwencai
    q = f"{target} 最近{int(days)}日 {fields}"
    resp = query_iwencai("hithink-market-query", q, limit=int(days))
    best = _first_row(resp)
    floor = max(1, int(min_rows or 0))
    if len(_row_dates(best)) < floor:
        time.sleep(1.5)
        cand = _first_row(query_iwencai("hithink-market-query", q,
                                        limit=int(days), use_cache=False))
        if len(_row_dates(cand)) > len(_row_dates(best)):
            best = cand
    if not _row_dates(best):
        err = (resp or {}).get("error", "") if isinstance(resp, dict) else ""
        raise ProviderUnavailable(f"问财返回空/无日期字段：{err}")
    return best


class IwencaiProvider(RunnerProvider):
    def __init__(self):
        super().__init__("iwencai", "ths_family", iw_runner, key="IWENCAI_API_KEY")

    def fetch(self, capability: str, **params: Any) -> DataResult:
        if capability == "pattern_history":
            return self._fetch_pattern_history(**params)
        if capability == "index_history":
            return self._fetch_index_history(**params)
        return super().fetch(capability, **params)

    def _fetch_pattern_history(self, *, code: str = "", name: str = "",
                               days: int = 500, min_rows: int | None = None,
                               **_kw: Any) -> DataResult:
        """整段前复权历史（SRC-012）：一次取全，禁止补尾部/跨源拼接。

        返回 ``value`` = 结构化载荷：

        - ``row``：原始宽行（legacy 匹配需要全字段）
        - ``dates``：升序 8 位交易日（legacy 内部口径）
        - ``series``：规范化前复权收盘序列 ``[{date: YYYY-MM-DD, close}]``
        - ``adjust``：``qfq``（**存在**前复权字段）/ ``raw``（无 → 上层 fail-closed）
        - ``data_range``：``[起始日, 截止日]``（ISO）

        🆕 K 定标期修复：``adjust`` 只说明"存在前复权字段"，**不保证整段可用**——
        问财宽行实测可能只回 1 列前复权（=最新一日），其余历史列仍是不复权。
        ``metadata.qfq_coverage`` = 前复权收盘覆盖的交易日 / 该行全部交易日，
        由 ``pattern_edge.source_gate`` 要求达到 ``reg.QFQ_COVERAGE_MIN`` 才放行
        （legacy 主输出口径不变：``adjust`` 语义与取值维持原样）。
        """
        if not self.configured():
            raise ProviderUnavailable("IWENCAI_API_KEY 未设置")
        row = query_wide_row(str(name or code), int(days),
                             min_rows=min_rows or 0)
        dates = _row_dates(row)
        series: list[dict[str, Any]] = []
        for key, val in row.items():
            m = _QFQ_KEY.search(str(key))
            if not m:
                continue
            try:
                close = float(val)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            d = m.group(1)
            series.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "close": close})
        series.sort(key=lambda r: r["date"])
        data_range: list[str] | None = ([str(series[0]["date"]), str(series[-1]["date"])]
                                         if series else None)
        # 🆕 K 定标期修复：整段覆盖率（见 docstring）——分母=该行全部交易日。
        qfq_coverage = (len(series) / len(dates)) if dates else None
        value = {"row": row, "dates": dates, "series": series,
                 "adjust": "qfq" if series else "raw",
                 "data_range": data_range}
        return DataResult(
            value=value, source="iwencai", provider_family=self.identity.family,
            as_of=(data_range[1] if data_range else None), status="ok",
            capability="pattern_history",
            metadata={"rows": len(dates), "qfq_rows": len(series),
                      "qfq_coverage": qfq_coverage,
                      # SRC-012：腾讯 crosscheck 尚未实现（experimental 阶段），
                      # 显式记 not_evaluated —— 不得冒充"已一致"。
                      "consistency_status": "not_evaluated",
                      "crosscheck": "tencent:not_implemented"})

    def _fetch_index_history(self, *, name: str = "上证指数", days: int = 860,
                             min_rows: int | None = None, **_kw: Any) -> DataResult:
        """指数收盘序列（regime MA360 牛熊背景用）。

        🆕 v7.3.4 复审修复（第 3 项）：pattern 的 regime 对齐此前**直连问财**，
        失败即静默退化成"所有日期同环境"。现经 registry 取数并回传完整血缘，
        由 ``pattern_edge.source_gate`` 在不可用时 fail-closed。

        指数无复权概念，``adjust`` 恒为 ``"raw"``（该字段只描述本序列口径，
        不参与个股 qfq 闸门）。
        """
        if not self.configured():
            raise ProviderUnavailable("IWENCAI_API_KEY 未设置")
        row = query_wide_row(str(name), int(days), min_rows=min_rows or 0,
                             fields="交易日期 收盘价")
        series: list[dict[str, Any]] = []
        for key, val in row.items():
            m = _CLOSE_KEY.match(str(key))
            if not m:
                continue
            try:
                close = float(val)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            d = m.group(1)
            series.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "close": close})
        series.sort(key=lambda r: r["date"])
        data_range: list[str] | None = ([str(series[0]["date"]), str(series[-1]["date"])]
                                         if series else None)
        value = {"series": series, "dates": [r["date"] for r in series],
                 "closes": [r["close"] for r in series],
                 "adjust": "raw", "data_range": data_range, "target": str(name)}
        return DataResult(
            value=value, source="iwencai", provider_family=self.identity.family,
            as_of=(data_range[1] if data_range else None),
            status="ok" if series else "unavailable", capability="index_history",
            metadata={"rows": len(series),
                      "consistency_status": "not_evaluated",
                      "crosscheck": "not_applicable:index"})
