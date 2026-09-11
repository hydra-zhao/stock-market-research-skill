#!/usr/bin/env python3
"""zt_pool_ak.py — 接力情绪四路 AKShare 东财股池降级（问财 401/配额耗尽时兜底）

背景（2026-08-19）：quick 的 v6.5 接力情绪四路（昨日涨停溢价/昨日连板晋级率/
一字板/涨跌家数）是问财单路，且 v6.5 原文"缺失时 TL;DR 对应行自动省略，
不触发降级补跑"——配额耗尽日这四路静默消失，养家裁决（溢价正负）与接力
温度（晋级率）开天窗。同日实测东财股池接口与问财路口径分毫不差
（stock_zt_pool_previous_em 涨跌幅均值 -2.56% == 本地问财路 -2.56%），
且零配额、datacenter 系接口不受 push2his 限流断连影响。

数据源（AKShare · 东财股池，全部零配额）：
- stock_zt_pool_previous_em(date=T)   昨日涨停股池（T日表现）→ 溢价 + 晋级率
- stock_zt_pool_em(date=T)            今日涨停股池 → 一字板（近似口径）+ 昨日板数对照
- stock_zt_pool_em(date=前一交易日)    昨日涨停股池 → 昨日连板名单（连板数≥2）
- stock_market_activity_legu()        乐咕市场广度 → 涨跌家数（盘后=收盘定格值）

口径标注：
- 股池口径≈非ST 10cm/20cm 涨停（东财股池不含5%ST板），与问财路"非ST"一致；
- 一字板无直接字段 → 近似=首次封板时间在竞价撮合时段（0925xx）且炸板次数 0，输出标注；
- 涨跌家数走乐咕实时快照，盘后=当日定格，盘中=半成品（quick 盘中本就降级）。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.calendar import trading_day

# 段落标签与 builders.build_market_quick 的问财路同名——
# 降级输出直接被 round1_v2 的 _premium_stats/_promotion_stats/_advance_decline/
# _extract_count 消费，解析器零改动
LABEL_PREMIUM = "昨日涨停表现"
LABEL_PROMOTION = "昨日连板表现"
LABEL_YIZI = "一字板"
LABEL_AD = "涨跌家数"

_POOL_CACHE = {}  # 进程内缓存：4 个任务共享 2-3 次 HTTP 调用


# ---------- 数据拉取（ak 可注入，测试用） ----------

def _cached(key, fn):
    if key not in _POOL_CACHE:
        _POOL_CACHE[key] = fn()
    return _POOL_CACHE[key]


def clear_cache():
    _POOL_CACHE.clear()


def _prev_trade_date(ak, date: str) -> str | None:
    """date 的前一交易日（YYYYMMDD）。工具交易日历取不到 → None。"""
    try:
        df = _cached("trade_cal", ak.tool_trade_date_hist_sina)
        dates = sorted(str(d)[:10].replace("-", "")
                       for d in df["trade_date"].tolist())
        prev = [d for d in dates if d < date]
        return prev[-1] if prev else None
    except Exception:
        return None


def _pool(ak, date: str):
    """涨停股池（某交易日）→ DataFrame | None"""
    try:
        df = _cached(f"zt_{date}", lambda: ak.stock_zt_pool_em(date=date))
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def _prev_pool(ak, date: str):
    """昨日涨停股池（date=T 日，内容为 T-1 涨停股的 T 日表现）→ DataFrame | None"""
    try:
        df = _cached(f"prev_{date}", lambda: ak.stock_zt_pool_previous_em(date=date))
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def _activity(ak) -> dict:
    """乐咕市场广度 → {'up': int, 'down': int}；异常 → {}"""
    try:
        df = _cached("legu", ak.stock_market_activity_legu)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    try:
        item = dict(zip(df["item"], df["value"]))
        return {"up": int(item["上涨"]), "down": int(item["下跌"])}
    except Exception:
        return {}


# ---------- 解析与计算 ----------

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def premium_rows(prev_df) -> list:
    """昨日涨停股池 → [(代码, 名称, 涨跌幅%, 昨日涨停统计'N天M板')]"""
    out = []
    if prev_df is None:
        return out
    for _, r in prev_df.iterrows():
        chg = _num(r.get("涨跌幅"))
        if chg is None:
            continue
        out.append((str(r.get("代码") or "").strip(),
                    str(r.get("名称") or "").strip(),
                    chg, str(r.get("涨停统计") or "").strip()))
    return out


def promotion_rows(prev_df, yday_df) -> tuple[list, str]:
    """昨日连板股（昨日股池连板数≥2）× 今日涨跌幅（昨涨停股池按代码对照）
    → ([(代码, 名称, 昨日连板数, 涨跌幅%)], 状态串)。第二值当前为占位 'ok'
    （调用方未使用；v6.9.44 审计修复：docstring 原写"昨日日期"与实际返回不符）；
    昨日股池缺失 → ([], '')"""
    if prev_df is None or yday_df is None:
        return [], ""
    chg_of = {}
    for _, r in prev_df.iterrows():
        chg = _num(r.get("涨跌幅"))
        code = str(r.get("代码") or "").strip()
        if code and chg is not None:
            chg_of[code] = chg
    out = []
    for _, r in yday_df.iterrows():
        n = _num(r.get("连板数"))
        if n is None or n < 2:
            continue
        code = str(r.get("代码") or "").strip()
        if code not in chg_of:
            continue
        out.append((code, str(r.get("名称") or "").strip(), int(n), chg_of[code]))
    return out, "ok"


def yizi_rows(today_df) -> list:
    """一字板近似口径：首次封板时间在集合竞价撮合时段（0925xx）且全天炸板次数 0
    → [(代码, 名称, 连板数)]。⚠️ 东财股池无一字字段，秒板（09:26后封）不计入。
    实测 8/19：金健米业封板时间 092502（非 092500），故用 0925 前缀而非精确相等。"""
    out = []
    if today_df is None:
        return out
    for _, r in today_df.iterrows():
        t = str(r.get("首次封板时间") or "").strip()
        zb = _num(r.get("炸板次数"))
        if t.startswith("0925") and zb == 0:
            out.append((str(r.get("代码") or "").strip(),
                        str(r.get("名称") or "").strip(),
                        int(_num(r.get("连板数")) or 1)))
    return out


# ---------- 渲染（iw 兼容 markdown 表，解析器零改动） ----------

def _table(header: list, rows: list) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def render_premium(rows: list, t: str) -> str:
    tbl = _table(["序号", "代码", "名称", f"涨跌幅[{t}]", "涨停统计"],
                 [(i + 1, c, n, round(g, 2), s)
                  for i, (c, n, g, s) in enumerate(rows)])
    return (tbl + f"\n\n_ak_zt: {len(rows)}/{len(rows)} rows | "
                  f"东财昨日涨停股池（{t} 口径，≈非ST）_")


def render_promotion(rows: list, t: str, pt: str) -> str:
    if not rows:
        return "（昨日无连板股或昨日股池缺失）"
    tbl = _table(["序号", "代码", "名称", "昨日连板数", f"涨跌幅[{t}]"],
                 [(i + 1, c, n, b, round(g, 2))
                  for i, (c, n, b, g) in enumerate(rows)])
    return (tbl + f"\n\n_ak_zt: {len(rows)}/{len(rows)} rows | "
                  f"昨日（{pt}）连板数≥2 × 今日（{t}）涨跌幅 · 东财股池对照_")


def render_yizi(rows: list, t: str) -> str:
    tbl = _table(["序号", "代码", "名称", "连板数"],
                 [(i + 1, c, n, b) for i, (c, n, b) in enumerate(rows)])
    return (tbl + f"\n\n_ak_zt: {len(rows)}/{len(rows)} rows | "
                  f"近似口径：竞价封死(0925xx)且全天0炸板 · 东财股池（{t}）_")


def render_ad(act: dict, t: str) -> str:
    return (f"- **上涨家数[{t}]**: {act['up']}\n"
            f"- **下跌家数[{t}]**: {act['down']}\n\n"
            f"_ak_zt: 乐咕市场广度快照（盘后=当日定格，盘中=半成品）_")


# ---------- dispatch 入口 ----------

def fetch_render(which: str, ak, t: str) -> tuple:
    """取数+渲染（ak 可注入，测试用）。返回 (ok, body)。"""
    if which == "premium":
        rows = premium_rows(_prev_pool(ak, t))
        if rows:
            return True, render_premium(rows, t)
        return False, "昨日涨停股池为空/异常"
    if which == "promotion":
        pt = _prev_trade_date(ak, t)
        if not pt:
            return False, "交易日历缺失，无法定位前一交易日"
        rows, _ = promotion_rows(_prev_pool(ak, t), _pool(ak, pt))
        if rows:
            return True, render_promotion(rows, t, pt)
        return False, "昨日连板股池为空/异常（昨日无连板或池缺失）"
    if which == "yizi":
        df = _pool(ak, t)
        if df is not None:
            return True, render_yizi(yizi_rows(df), t)
        return False, "今日涨停股池为空/异常"
    if which == "ad":
        act = _activity(ak)
        if act:
            return True, render_ad(act, t)
        return False, "乐咕市场广度快照为空/异常"
    return False, f"未知降级任务: {which}"


def run_akshare_ztpool(which: str, ak=None, today: str = None) -> tuple:
    """dispatch 入口：which ∈ premium|promotion|yizi|ad。
    返回 (label, body, ok, elapsed, 'ak')——与 etf_ak 同型。"""
    label = {"premium": LABEL_PREMIUM, "promotion": LABEL_PROMOTION,
             "yizi": LABEL_YIZI, "ad": LABEL_AD}.get(which, which)
    t0 = time.time()
    try:
        if ak is None:
            import akshare as ak
        ok, body = fetch_render(which, ak, today or trading_day())
    except Exception as e:
        ok, body = False, f"AK股池降级路异常: {e}"
    elapsed = time.time() - t0
    if not ok:
        body = f"[ak ERR] {body}"
    return (label, body, ok, elapsed, "ak")
