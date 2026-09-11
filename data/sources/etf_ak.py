#!/usr/bin/env python3
"""etf_ak.py — 国家队ETF 份额 AKShare 降级路（问财 401/配额耗尽时兜底）

背景（2026-08-19）：market/market core 的「国家队ETF」路是问财单路
（iwencai_api.py MARKET_IWENCAI），问财日配额耗尽即开天窗。本模块照
seat_profile.fetch_lhb_with_fallback 的降级模式，用交易所官网份额数据兜底。

数据源（AKShare）：
- 沪市 8 只：fund_etf_scale_sse(date) — 上交所每日 ETF 份额历史，按日期可取 ✅
- 深市 2 只（159915/159919）：fund_etf_scale_szse() — 仅最新快照、无日期参数，
  无法算单日 Δ → 快照行展示但净申购合计不含深市（诚实标注 8/10 口径）⚠️
- 净值：fund_etf_spot_em 单次快照（昨收列=份额数据日 T-1 收盘，天然对齐口径）；
  spot 解析失败的个别代码走 fund_etf_hist_em 逐只兜底（断连退避重试 1 次）。
  均为收盘价代理净值（与问财路"最新净值"口径略有出入，输出标注）

日期发现：ETF 份额 T+1 披露，且 calendar 不感知法定节假日 → 不猜日期，
从 trading_day() 前一天起向前步进试拉，首个非空日=最新真实数据日，
再往前一个非空日=对照日（最多回看 LOOKBACK_DAYS 天）。

已探明无更优替代（2026-08-19 实测）：金十无 ETF 份额能力；wind 只有最新快照
（wind_get_fund_price_indicators 基金规模/净值）且单次限 3 标的，申赎明细为季报口径。
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.calendar import trading_day

LABEL = "国家队ETF"
LOOKBACK_DAYS = 10        # 向前步进找真实数据日的上限（覆盖长假）
PRICE_SLEEP = 0.5         # 逐只拉收盘价的节流（秒）——东财对快速连调会 RemoteDisconnected

# (代码, 简称, 市场)——与 iwencai_api.py MARKET_IWENCAI「国家队ETF」路同一清单
ETF_LIST = [
    ("510300", "沪深300ETF", "sse"),
    ("510050", "50ETF", "sse"),
    ("510500", "500ETF", "sse"),
    ("512100", "1000ETF", "sse"),
    ("588000", "科创50", "sse"),
    ("588080", "科创板50", "sse"),
    ("159915", "创业板ETF", "szse"),
    ("159919", "沪深300ETF嘉实", "szse"),
    ("510330", "华夏300", "sse"),
    ("563300", "中证2000", "sse"),
]
SSE_CODES = [c for c, _, m in ETF_LIST if m == "sse"]
SZSE_CODES = [c for c, _, m in ETF_LIST if m == "szse"]


# ---------- 数据拉取（ak 可注入，测试用） ----------

def _sse_shares(date: str, ak) -> dict:
    """上交所某日 ETF 份额 → {code: shares(份)}；无数据/异常 → {}"""
    try:
        df = ak.fund_etf_scale_sse(date=date)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    # 列序实测：序号/基金代码/基金简称/ETF类型/统计日期/基金份额（列名随 akshare 版本
    # 可能带乱码，按位置取第 2/6 列最稳）
    code_col, share_col = df.columns[1], df.columns[5]
    out = {}
    for _, r in df.iterrows():
        code = str(r[code_col]).strip()
        if code in SSE_CODES:
            try:
                out[code] = float(r[share_col])
            except (TypeError, ValueError):
                continue
    return out


def _szse_snapshot(ak) -> dict:
    """深交所 ETF 最新份额快照（无日期参数、无历史）→ {code: (shares, nav)}"""
    try:
        df = ak.fund_etf_scale_szse()
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    out = {}
    for _, r in df.iterrows():
        code = str(r.get("基金代码") or "").strip()
        if code not in SZSE_CODES:
            continue
        try:
            shares = float(r.get("基金份额"))
        except (TypeError, ValueError):
            continue
        try:
            nav = float(r.get("净值"))
        except (TypeError, ValueError):
            nav = None
        out[code] = (shares, nav)
    return out


def _spot_prices(ak) -> dict:
    """东财 ETF 实时快照单次调用 → {code: (数据日期YYYYMMDD, 最新价, 昨收)}。

    主价格源：1 次调用覆盖全部 ETF（逐只 hist 连调会被东财 RemoteDisconnected，
    2026-08-19 实测）。昨收列恰好=份额数据日（T-1）收盘价，与降级路口径天然对齐。
    """
    try:
        df = ak.fund_etf_spot_em()
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    out = {}
    for _, r in df.iterrows():
        code = str(r.get("代码") or "").strip()
        if code not in SSE_CODES:
            continue
        try:
            spot_date = str(r.get("数据日期") or "").replace("-", "")
            latest_px = float(r.get("最新价"))
            prev_px = float(r.get("昨收"))
        except (TypeError, ValueError):
            continue
        if spot_date:
            out[code] = (spot_date, latest_px, prev_px)
    return out


def resolve_price(code: str, share_date: str, spot_map: dict) -> float | None:
    """从 spot 快照解析 share_date 当日收盘价：
    spot日期==share_date → 最新价（盘前/当日未开盘场景）；
    spot日期>share_date → 昨收（盘后场景，昨收=share_date 收盘）；
    其余（spot 陈旧/异常）→ None（调用方再走 hist 兜底）。"""
    s = spot_map.get(code)
    if not s:
        return None
    spot_date, latest_px, prev_px = s
    if spot_date == share_date:
        return latest_px
    if spot_date > share_date:
        return prev_px
    return None


def _close_price(code: str, date: str, ak, sleep_fn=time.sleep) -> float | None:
    """ETF 某日收盘价 hist 兜底（仅 spot 解析失败时逐只调用）；
    瞬时断连（东财反爬）退避重试 1 次；失败 → None"""
    for attempt in range(2):
        try:
            h = ak.fund_etf_hist_em(symbol=code, period="daily",
                                    start_date=date, end_date=date, adjust="")
        except Exception:
            if attempt == 0:
                sleep_fn(1.5)
                continue
            return None
        if h is None or h.empty:
            return None
        try:
            return float(h["收盘"].iloc[-1])
        except (KeyError, TypeError, ValueError, IndexError):
            return None
    return None


def find_share_dates(ak, today: str = None, lookback: int = LOOKBACK_DAYS):
    """从 trading_day()-1 起向前步进，找最近两个有沪市份额数据的日期。
    返回 (latest_date, prev_date)；找不到则对应位为 None。"""
    t = datetime.strptime(today or trading_day(), "%Y%m%d")
    found = []
    for i in range(1, lookback + 1):
        d = (t - timedelta(days=i)).strftime("%Y%m%d")
        if _sse_shares(d, ak):
            found.append(d)
            if len(found) == 2:
                break
    latest = found[0] if found else None
    prev = found[1] if len(found) > 1 else None
    return latest, prev


# ---------- 计算与渲染 ----------

def compute_rows(latest_map: dict, prev_map: dict, prices: dict) -> tuple[list, float]:
    """沪市行：Δ份额×收盘价=净申购估算(亿元)。返回 (rows, 合计亿元)。
    row = (code, name, prev亿份, latest亿份, Δ亿份, price, 净申购亿 or None)"""
    name_of = {c: n for c, n, _ in ETF_LIST}
    rows, total = [], 0.0
    for code in SSE_CODES:
        if code not in latest_map or code not in prev_map:
            continue
        prev_y = prev_map[code] / 1e8
        latest_y = latest_map[code] / 1e8
        d_y = latest_y - prev_y
        px = prices.get(code)
        amt = d_y * px if px is not None else None  # 亿份×元 = 亿元
        if amt is not None:
            total += amt
        rows.append((code, name_of[code], prev_y, latest_y, d_y, px, amt))
    return rows, total


def render(latest: str, prev: str, rows: list, total: float,
           szse_snap: dict, monitored: int) -> str:
    """渲染降级输出（markdown）。净申购=Σ(Δ份额×收盘价)，口径诚实标注。"""
    def _f(v, fmt="{:.2f}"):
        return fmt.format(v) if isinstance(v, (int, float)) else "—"

    name_of = {c: n for c, n, _ in ETF_LIST}
    lines = [f"**国家队ETF 申赎（AKShare 降级路 · 交易所官网份额）**",
             f"数据日期：{latest}（对照 {prev}）· T+1 披露 · 净值用收盘价代理",
             "",
             "| 代码 | 简称 | 份额前(亿) | 份额现(亿) | Δ份额(亿) | 收盘价 | 净申购估算(亿) |",
             "|------|------|--:|--:|--:|--:|--:|"]
    for code, name, prev_y, latest_y, d_y, px, amt in rows:
        lines.append(f"| {code} | {name} | {prev_y:.2f} | {latest_y:.2f} "
                     f"| {d_y:+.2f} | {_f(px, '{:.3f}')} | {_f(amt, '{:+.1f}')} |")
    lines.append(f"| **沪市合计** | | | | | | **{total:+.1f}** |")
    for code in SZSE_CODES:
        snap = szse_snap.get(code)
        if snap:
            lines.append(f"| {code} | {name_of[code]} | — | {snap[0] / 1e8:.2f} "
                         f"| 无历史接口 | {_f(snap[1], '{:.3f}')} | 未计入 |")
        else:
            lines.append(f"| {code} | {name_of[code]} | — | — | 无历史接口 | — | 未计入 |")
    lines.append("")
    lines.append(f"⚠️ 口径：深市 2 只（159915/159919）深交所仅披露最新快照、无日期历史，"
                 f"净申购合计仅含沪市已监测 {monitored} 只；"
                 f"与问财路「最新净值」口径相比，本路用收盘价代理净值，数值供方向参考。")
    return "\n".join(lines)


def fetch_and_render(ak=None, sleep_fn=time.sleep, today: str = None) -> tuple:
    """主流程：找日期 → 拉份额/价格 → 渲染。返回 (ok, body_or_err)。"""
    if ak is None:
        import akshare as ak
    latest, prev = find_share_dates(ak, today=today)
    if not latest:
        return False, "交易所份额历史向前回溯均无数据（网络或接口异常）"
    if not prev:
        return False, f"仅找到 {latest} 单日份额，无对照日无法算 Δ"
    latest_map = _sse_shares(latest, ak)
    prev_map = _sse_shares(prev, ak)
    # 价格：spot 单次调用为主（昨收列=T-1 收盘，天然对齐份额数据日）；
    # 仅 spot 解析失败的个别代码走 hist 兜底（逐只连调易被东财断连，尽量少调）
    spot_map = _spot_prices(ak)
    prices = {}
    for code in SSE_CODES:
        if code not in latest_map:
            continue
        px = resolve_price(code, latest, spot_map)
        if px is None:
            px = _close_price(code, latest, ak, sleep_fn=sleep_fn)
            sleep_fn(PRICE_SLEEP)
        prices[code] = px
    rows, total = compute_rows(latest_map, prev_map, prices)
    if not rows:
        return False, f"{latest} 份额表未覆盖监测清单"
    szse_snap = _szse_snapshot(ak)
    return True, render(latest, prev, rows, total, szse_snap, len(rows))


def run_akshare_etf() -> tuple:
    """dispatch 入口：返回 (label, body_md, ok, elapsed_sec, 'ak')——与 cffex 同型"""
    t0 = time.time()
    try:
        ok, body = fetch_and_render()
    except Exception as e:
        ok, body = False, f"[ak ERR] ETF降级路异常: {e}"
    elapsed = time.time() - t0
    if not ok:
        body = f"[ak ERR] {body}"
    else:
        body += f"\n\n_ak: {elapsed:.1f}s | 数据源: 上交所/深交所官网 via AKShare（问财配额降级）_"
    return (LABEL, body, ok, elapsed, "ak")
