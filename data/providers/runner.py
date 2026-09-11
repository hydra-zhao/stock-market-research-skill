"""Bridge provider results into the stable round1 markdown runner contract."""
from __future__ import annotations

import json
import time

from .registry import get_registry


def task(capability: str, **params) -> str:
    return json.dumps({"capability": capability, "params": params}, ensure_ascii=False,
                      sort_keys=True)


def _table(rows: list[dict]) -> str:
    if not rows:
        return "[provider empty]"
    keys = []
    for row in rows[:5]:
        for key in row:
            if key not in keys:
                keys.append(key)
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(str(row.get(k, "")) for k in keys) + " |" for row in rows]
    return "\n".join(lines)


def _render(capability: str, value, params: dict) -> str:
    if isinstance(value, dict) and "rendered" in value:
        return str(value["rendered"])
    if capability == "daily_k":
        packed = {}
        for x in value or []:
            day = str(x.get("date") or "").replace("-", "")
            if len(day) != 8:
                continue
            for key, source_key in (("交易日期", "date"), ("开盘价", "open"),
                                    ("收盘价", "close"), ("最高价", "high"),
                                    ("最低价", "low")):
                packed[f"{key}[{day}]"] = x.get(source_key)
            packed[f"成交量[{day}]"] = round(float(x.get("volume") or 0) / 100)
            packed[f"换手率[{day}]"] = ""
        from tech.kline import fmt_kline
        return fmt_kline([packed]) + f"\n_provider: {len(value or [])}/{len(value or [])} rows_"
    if capability in {"weekly_k", "monthly_k"}:
        rows = [{"交易日期": x.get("date"), "开盘价": x.get("open"), "收盘价": x.get("close"),
                 "最高价": x.get("high"), "最低价": x.get("low"), "成交量": x.get("volume"),
                 "成交额": x.get("turnover")} for x in (value or [])]
        body = _table(rows) + f"\n_provider: {len(rows)}/{len(rows)} rows_"
        if capability == "weekly_k":
            # 对齐旧问财"周线技术"口径：重采样行之外补周线 MA5/MA10/MA20 与
            # 20 周均线方向（MA20 当前窗口 vs 上一窗口，事实性斜率，非决策）。
            closes = [float(x["close"]) for x in (value or []) if x.get("close") is not None]
            mas = []
            for n in (5, 10, 20):
                v = sum(closes[-n:]) / n if len(closes) >= n else None
                mas.append(f"MA{n}=" + (f"{v:.2f}" if v is not None else "样本不足"))
            if len(closes) >= 21:
                cur = sum(closes[-20:]) / 20
                prev = sum(closes[-21:-1]) / 20
                direction = "上行" if cur > prev else ("下行" if cur < prev else "持平")
            else:
                direction = "样本不足(需21周)"
            body += f"\n_周线 {' '.join(mas)}｜20周均线方向: {direction}_"
        return body
    if capability == "market_daily_dump":
        from sources import market_dump
        metric = params.get("metric", "ztdt")
        series = market_dump.daily_zt_dt_amt(start=params.get("start"), end=params.get("end"))
        rows = []
        for date, vals in sorted(series.items()):
            row = {"date": date}
            if metric == "amount":
                row["成交额"] = vals["amt"]
            else:
                row.update({"涨停家数": vals["zt"], "跌停家数": vals["dt"]})
            rows.append(row)
        limit = int(params.get("limit") or 30)
        rows = rows[-limit:]
        return _table(rows) + f"\n_provider: {len(rows)}/{len(rows)} rows_"
    if capability in {"limit_up_pool", "limit_down_pool", "limit_break_pool"}:
        from sources.hithink_runner import render_break_pool, render_down_pool, render_pool
        total, items = value.get("total"), value.get("items", [])
        renderer = {"limit_up_pool": render_pool, "limit_down_pool": render_down_pool,
                    "limit_break_pool": render_break_pool}[capability]
        return renderer(total, items).replace("_ht ", "_fuyao ")
    if capability == "limit_ladder":
        rows = []
        items = (value or {}).get("item", [])
        latest = items[0] if items else {}
        for arr in (latest.get("boards") or {}).values():
            for item in arr or []:
                rows.append({"股票代码": item.get("thscode") or item.get("ticker", ""),
                             "股票简称": item.get("name", ""),
                             "连续涨停天数": item.get("board_num") or item.get("continue_day_cnt", "")})
        return _table(rows) + f"\n_fuyao: {len(rows)}/{len(rows)} rows_"
    if capability == "lhb":
        from sources.hithink_runner import render_dragon
        return render_dragon(value or {}, params.get("board_type", "all"))
    if isinstance(value, list):
        return _table(value) + f"\n_provider: {len(value)}/{len(value)} rows_"
    if hasattr(value, "to_dict"):
        rows = value.head(int(params.get("limit") or 20)).to_dict("records")
        return _table(rows) + f"\n_provider: {len(rows)} rows_"
    return json.dumps(value, ensure_ascii=False, default=str)


def run_provider(label: str, query: str):
    t0 = time.time()
    try:
        payload = json.loads(query)
        capability = payload["capability"]
        params = dict(payload.get("params") or {})
        params.setdefault("label", label)
        result = get_registry().route(capability, **params)
        if not result.usable:
            raw = result.metadata.get("raw_status", result.status)
            return label, f"[provider {str(raw).upper()}] {result.error or 'data unavailable'}", False, time.time() - t0, "provider"
        body = _render(capability, result.value, params)
        provenance = (f"\n_provenance: source={result.source} family={result.provider_family} "
                      f"status={result.status} as_of={result.as_of or 'unknown'} "
                      f"fallback_from={result.fallback_from or '-'}_")
        return label, body + provenance, True, time.time() - t0, result.source
    except Exception as exc:
        return label, f"[provider ERR] {type(exc).__name__}: {exc}", False, time.time() - t0, "provider"
