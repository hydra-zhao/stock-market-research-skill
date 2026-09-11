#!/usr/bin/env python3
"""ths_limitup.py — 同花顺数据中心涨停行情 dataapi 降级源（v7.0.9）

背景（2026-08-28）：问财 OpenAPI 按日配额，耗尽日（HTTP 401）核心情绪五路
（涨停板/跌停板/炸板股/连板天梯/一字板）裸奔——MX 降级只有计数与
天梯/炸板个股表，涨停池无个股明细更无涨停原因（首板题材归类 v6.9.27 断粮）。
实测同花顺数据中心官方 web 接口（data.10jqka.com.cn/dataapi/limit_up/）
零配额、免登录、支持历史日期，涨停池自带 reason_type 涨停原因（问财同款
"+"拆词格式）——降级链新增 THS 档：iw 失败 → MX → **THS** → AK 股池。

端点（从前端 SPA JS 挖出并实测，2026-08-28）：
- limit_up_pool         涨停池：81只全量+reason_type/封板类型/封单额/开板次数/
                        首末封板时间/几天几板/换手；响应自带 limit_up_count
                        （含 open_num=炸板家数）与 limit_down_count
- continuous_limit_up   连板天梯：按高度分组 code_list
- block_top             题材热度：题材聚类+涨停家数+高度+连续板块天数+逐股长文
                        reason_info（首板题材归类旁证数据源，quick 主链不新增路）

口径标注（影子期对账 2026-08-28）：
- 涨停 THS 81 / MX 83 / AK 东财 82（±2 家口径差，THS≈非ST 与 AK 一致）
- 跌停 THS 1 vs MX 3（THS 口径更严，计数路标注"计数口径"）
- web 接口无 SLA 无契约文档，字段可能漂移——按 v7.0.8 对账哨兵先例，
  影子跑数日后复盘确认再转正。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "https://data.10jqka.com.cn/dataapi/limit_up"
# field 白名单：逐项 ID 对应 reason_type/封板类型/封单额等（缺省时仅返回 6 个基础列）
FIELD_ZT = ("199112,10,9001,330323,330324,330325,9002,330329,"
            "133971,133970,1968584,3475914,9003,9004")
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Referer": "https://data.10jqka.com.cn/datacenterph/limitup/limtupInfo.html",
}
_TIMEOUT = 15

# 段落标签与 builders.build_market_quick 的问财路同名——
# 降级输出直接被 round1_v2 的 _extract_count/_parse_iw_table/_max_ladder 消费
LABELS = {
    "zt_pool": "涨停板",
    "dt_count": "跌停板",
    "bomb_count": "炸板股",
    "ladder": "连板天梯",
    "yizi": "一字板",
}

_POOL_CACHE = {}  # 进程内缓存：同交易日 涨停板/一字板/跌停计数/炸板计数 共享 1 次 HTTP


# ---------- HTTP（getter 可注入，测试零网络） ----------

def _default_getter(path: str, params: dict) -> dict:
    # 🆕 v7.2.13 接入 netguard 受控出口（v7.2.6 普查漏此文件；ths_line 同型已接）
    from common.netguard import http_get
    r = http_get(f"{BASE_URL}/{path}", params=params,
                 headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _get_json(path: str, params: dict, getter=None) -> dict:
    return (getter or _default_getter)(path, params)


def _cached(key, fn):
    if key not in _POOL_CACHE:
        _POOL_CACHE[key] = fn()
    return _POOL_CACHE[key]


def clear_cache():
    _POOL_CACHE.clear()


# ---------- 取数与解析 ----------

def fetch_pool(date: str, getter=None) -> dict:
    """涨停池原始响应（status_code!=0 或异常 → {}）。同日共享缓存。"""
    return _cached(f"pool_{date}_{id(getter)}", lambda: _get_json(
        "limit_up_pool",
        {"page": 1, "limit": 100, "field": FIELD_ZT, "filter": "HS,GEM2STAR",
         "order_field": "330324", "order_type": "0", "date": date},
        getter))


def _rows_of(pool: dict) -> list:
    return ((pool.get("data") or {}).get("info") or []) if pool else []


def _counts_of(pool: dict) -> dict:
    d = (pool.get("data") or {}) if pool else {}
    zt = ((d.get("limit_up_count") or {}).get("today") or {})
    dt = ((d.get("limit_down_count") or {}).get("today") or {})
    return {"zt": zt.get("num"), "bomb": zt.get("open_num"), "dt": dt.get("num")}


def zt_rows(pool: dict) -> list:
    """涨停池 → [(代码,名称,涨跌幅%,几天几板,涨停原因,封板类型,封单额亿,开板次数,换手%)]"""
    out = []
    for r in _rows_of(pool):
        try:
            chg = round(float(r.get("change_rate") or 0), 2)
        except (TypeError, ValueError):
            chg = 0.0
        oa = r.get("order_amount")
        try:
            oa_yi = round(float(oa) / 1e8, 2) if oa else 0.0
        except (TypeError, ValueError):
            oa_yi = 0.0
        on = r.get("open_num")
        out.append((str(r.get("code") or ""), str(r.get("name") or ""), chg,
                    str(r.get("high_days") or "").strip(),
                    str(r.get("reason_type") or "").strip(),
                    str(r.get("limit_up_type") or "").strip(),
                    oa_yi, int(on) if on is not None else 0,
                    r.get("turnover_rate")))
    return out


def yizi_rows(pool: dict) -> list:
    """一字板：封板类型含"一字"（THS 精确字段，优于 AK 东财竞价近似口径）
    → [(代码, 名称, 连板数)]。连板数从 几天几板 文本解析（首板=1）。"""
    out = []
    for r in _rows_of(pool):
        if "一字" not in str(r.get("limit_up_type") or ""):
            continue
        hd = str(r.get("high_days") or "")
        boards = 1
        if "板" in hd:
            import re
            m = re.search(r"(\d+)板", hd)
            if m:
                boards = int(m.group(1))
        out.append((str(r.get("code") or ""), str(r.get("name") or ""), boards))
    return out


def fetch_ladder(date: str, getter=None) -> list:
    """连板天梯 → [(代码, 名称, 连续涨停天数, 高度板)] 高度降序。
    status_code!=0 或 data 空 → []（真空天梯合法语义）；传输异常向上抛
    （由 run_ths_limitup 转 [ths ERR]，异常≠空市况，不得伪装 [ths empty]）"""
    j = _cached(f"ladder_{date}_{id(getter)}", lambda: _get_json(
        "continuous_limit_up",
        {"page": 1, "limit": 100, "date": date, "filter": "HS,GEM2STAR",
         "order_field": "330324", "order_type": "0"}, getter))
    data = (j.get("data") or []) if (j or {}).get("status_code") == 0 else []
    out = []
    for grp in data:
        h = grp.get("height")
        for c in (grp.get("code_list") or []):
            out.append((str(c.get("code") or ""), str(c.get("name") or ""),
                        int(c.get("continue_num") or 0), int(h or 0)))
    out.sort(key=lambda x: -x[3])
    return out


def fetch_block_top(date: str, getter=None) -> list:
    """题材热度 → [{name, limit_up_num, continuous_plate_num, high, days, stocks}]
    （首板题材归类旁证：板块涨停计数=主线确认①数据源；quick 主链不新增路，独立调用）"""
    try:
        j = _cached(f"block_{date}_{id(getter)}", lambda: _get_json(
            "block_top",
            {"page": 1, "limit": 20, "date": date, "filter": "HS,GEM2STAR",
             "order_field": "330324", "order_type": "0"}, getter))
        data = (j.get("data") or []) if j.get("status_code") == 0 else []
    except Exception:
        return []
    out = []
    for b in data:
        out.append({"name": b.get("name"), "limit_up_num": b.get("limit_up_num"),
                    "continuous_plate_num": b.get("continuous_plate_num"),
                    "high": b.get("high"), "days": b.get("days"),
                    "stocks": [(str(c.get("code") or ""), str(c.get("name") or ""),
                                str(c.get("reason_info") or "").strip())
                               for c in (b.get("stock_list") or [])]})
    return out


# ---------- 渲染（iw 兼容 markdown 表，解析器零改动） ----------

def _table(header: list, rows: list) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _foot(n: int, note: str) -> str:
    # footer 格式对齐 _extract_count 的 N/N rows 约定（降级计数解析依赖）
    return f"_ths: {n}/{n} rows, 0.0s | {note}_"


def render_zt(rows: list, t: str) -> str:
    tbl = _table(["序号", "代码", "名称", "最新涨跌幅", "几天几板", "涨停原因",
                  "封板类型", "封单额(亿)", "开板次数"],
                 [(i + 1, c, n, g, hd, rs, lt, oa, on)
                  for i, (c, n, g, hd, rs, lt, oa, on, _tr) in enumerate(rows)])
    return (tbl + "\n\n" + _foot(len(rows),
            f"THS涨停池（{t}）· 涨停原因=首板题材归类数据源 · ≈非ST口径"))


def render_ladder(rows: list, t: str) -> str:
    if not rows:
        return "（THS连板天梯为空）"
    tbl = _table(["序号", "代码", "名称", "连续涨停天数", "高度板"],
                 [(i + 1, c, n, b, h) for i, (c, n, b, h) in enumerate(rows)])
    return tbl + "\n\n" + _foot(len(rows), f"THS连板天梯（{t}）_")


def render_yizi(rows: list, t: str) -> str:
    if not rows:
        return "[ths empty] 今日无一字板（封板类型=一字）"
    tbl = _table(["序号", "代码", "名称", "连板数"],
                 [(i + 1, c, n, b) for i, (c, n, b) in enumerate(rows)])
    return tbl + "\n\n" + _foot(len(rows), f"THS一字板（{t}）精确口径=封板类型含一字_")


def render_count(value, label: str, t: str, note: str) -> str:
    """计数口径段（跌停/炸板：THS 池响应自带家数，无个股明细——明细走 MX/AK 路）"""
    if value is None:
        return f"[ths empty] {label}计数缺失"
    v = int(value)
    return (f"- **{label}[{t}]**: {v}\n\n" + _foot(v, f"THS{label}计数口径（{t}）{note}_"))


def render_block_top(blocks: list, t: str) -> str:
    """题材热度榜（独立调试/归类旁证输出，非 quick 主链段落）"""
    if not blocks:
        return "（THS题材热度为空）"
    lines = ["| 排名 | 题材 | 涨停家数 | 连续板块天数 | 高度 |",
             "|------|------|------|------|------|"]
    for i, b in enumerate(blocks[:15]):
        lines.append(f"| {i + 1} | {b['name']} | {b['limit_up_num']} | "
                     f"{b['continuous_plate_num']} | {b['high']} |")
    return "\n".join(lines) + f"\n\n_ths: {len(blocks[:15])}/{len(blocks)} rows, 0.0s | THS题材热度（{t}）_"


# ---------- dispatch 入口 ----------

def fetch_render(which: str, getter, t: str) -> tuple:
    """取数+渲染（getter 可注入，测试用）。返回 (ok, body)。"""
    pool = None
    if which in ("zt_pool", "dt_count", "bomb_count", "yizi"):
        pool = fetch_pool(t, getter)
        if not pool or pool.get("status_code") != 0:
            return False, f"THS涨停池返回异常（status_code={pool.get('status_code') if pool else 'N/A'}）"
    if which == "zt_pool":
        rows = zt_rows(pool)
        if not rows:
            return True, f"[ths empty] THS涨停池为空（{t}）"
        return True, render_zt(rows, t)
    if which == "dt_count":
        return True, render_count(_counts_of(pool).get("dt"), "跌停家数", t,
                                  "·个股明细走MX/AK降级路")
    if which == "bomb_count":
        return True, render_count(_counts_of(pool).get("bomb"), "炸板家数", t,
                                  "·曾涨停未封板家数，个股明细走MX/AK降级路")
    if which == "yizi":
        return True, render_yizi(yizi_rows(pool), t)
    if which == "ladder":
        rows = fetch_ladder(t, getter)
        if not rows:
            return True, f"[ths empty] THS连板天梯为空（{t}）"
        return True, render_ladder(rows, t)
    return False, f"未知THS降级任务: {which}"


def run_ths_limitup(which: str, getter=None, today: str = None) -> tuple:
    """dispatch 入口：which ∈ zt_pool|dt_count|bomb_count|ladder|yizi。
    返回 (label, body, ok, elapsed, 'ths')——与 zt_pool_ak/etf_ak 同型。"""
    label = LABELS.get(which, which)
    t0 = time.time()
    try:
        if today is None:
            from common.calendar import trading_day
            today = trading_day().replace("-", "")
        ok, body = fetch_render(which, getter, today)
    except Exception as e:
        ok, body = False, f"THS降级路异常: {e}"
    elapsed = time.time() - t0
    if not ok:
        body = f"[ths ERR] {body}"
    return (label, body, ok, elapsed, "ths")
