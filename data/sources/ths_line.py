#!/usr/bin/env python3
"""ths_line.py — 同花顺行情 K线接口降级源（v7.0.9）

背景：kline/pattern/stock 的 历史K线路走问财，配额耗尽日（401）个股技术面
全断。实测同花顺行情接口（d.10jqka.com.cn/v6/line/）免登录免 cookie：
- /v6/line/{sym}/01/today.js    当日实时行（盘后=定格收盘）
- /v6/line/{sym}/01/{year}.js   全年日K（2025 全年 14KB 实测通过）

设计：解析 JSONP → 转问财 dict 格式（开盘价[YYYYMMDD] 等键）→ 直接喂
tech/kline.fmt_kline——均线/MACD/KDJ/量价异常检测/关键位阶梯全部继承，
解析器与展示零漂移。

字段序（实测）：date,open,high,low,close,volume(股),amount,换手率?,...
⚠️ 成交量 THS=股，问财 K线表头=手 → ÷100 对齐（量比/天量阈值口径一致）。
⚠️ 北交所（8xx/4xx/920 前缀）symbol 前缀 bj_ 未实测，失败按 ERR 优雅降级。
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.netguard import http_get  # noqa: E402  (v7.2.6 网络出口守卫)

LINE_URL = "https://d.10jqka.com.cn/v6/line/{sym}/01/{part}.js"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_TIMEOUT = 15

_YEARS_BACK = 2  # 60日窗口跨年时回溯上一年文件


def code_to_symbol(code: str) -> str:
    """6位代码 → THS symbol。北交所（8/4/920开头）=bj_，其余（沪/深/科创/创业）=hs_"""
    c = str(code).strip()
    if c.startswith(("8", "4", "920")):
        return f"bj_{c}"
    return f"hs_{c}"


def _default_getter(sym: str, part: str) -> str:
    r = http_get(LINE_URL.format(sym=sym, part=part),
                 headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.text


def _parse_jsonp(text: str) -> dict:
    """quotebridge_v6_line_hs_xxx_01_2025({...}) → {...}"""
    i, j = text.find("("), text.rfind(")")
    if i < 0 or j <= i:
        raise ValueError("JSONP 包裹格式异常")
    return json.loads(text[i + 1:j])


def _parse_rows(payload: dict) -> list:
    """payload.data="date,o,h,l,c,vol,amt,换手,...;..." → [(date,o,h,l,c,vol股,amt,换手)]"""
    out = []
    for chunk in str(payload.get("data") or "").split(";"):
        f = chunk.split(",")
        if len(f) < 7 or not f[0].isdigit() or len(f[0]) != 8:
            continue
        try:
            out.append((f[0], float(f[1]), float(f[2]), float(f[3]), float(f[4]),
                        float(f[5]), float(f[6]),
                        float(f[7]) if len(f) > 7 and f[7] else None))
        except (ValueError, IndexError):
            continue
    return out


def fetch_history(code: str, days: int = 60, getter=None) -> list:
    """近 N 个交易日日K（含当日实时行若晚于年文件末行）→ 日期升序 [(date,o,h,l,c,vol股,amt,换手)]"""
    getter = getter or _default_getter
    sym = code_to_symbol(code)
    year = datetime.now().year
    merged = {}
    for y in (year, year - _YEARS_BACK + 1):
        try:
            for row in _parse_rows(_parse_jsonp(getter(sym, str(y)))):
                merged[row[0]] = row
        except Exception:
            continue
    # 当日实时行补尾（年文件盘后可能未更新）
    try:
        for row in _parse_rows(_parse_jsonp(getter(sym, "today"))):
            if row[0] not in merged or merged[row[0]][4] != row[4]:
                merged[row[0]] = row
    except Exception:
        pass
    return [merged[d] for d in sorted(merged)][-max(int(days), 1):]


def to_iw_style(rows: list) -> dict:
    """THS 行 → 问财 K线 dict（键=字段名[YYYYMMDD]，成交量 股→手 ÷100）。
    直接喂 tech/kline.fmt_kline——技术指标/量价异常/关键位阶梯零漂移继承。"""
    row = {}
    for d, o, h, l, c, vol, amt, tr in rows:
        row[f"交易日期[{d}]"] = d
        row[f"开盘价[{d}]"] = o
        row[f"最高价[{d}]"] = h
        row[f"最低价[{d}]"] = l
        row[f"收盘价[{d}]"] = c
        row[f"成交量[{d}]"] = round(vol / 100)  # 股→手
        row[f"换手率[{d}]"] = tr if tr is not None else ""
    return row


# ---------- dispatch 入口 ----------

def run_ths_kline(query: str, getter=None) -> tuple:
    """dispatch 入口：query="code days"。返回 (label, body, ok, elapsed, 'ths')。"""
    t0 = time.time()
    parts = str(query).split()
    code = parts[0] if parts else ""
    try:
        days = int(parts[1]) if len(parts) > 1 else 60
    except ValueError:
        days = 60
    try:
        if not code:
            raise ValueError("缺代码")
        rows = fetch_history(code, days, getter)
        if not rows:
            raise ValueError("THS K线返回为空")
        from tech.kline import fmt_kline
        body = fmt_kline([to_iw_style(rows)])
        n = len(rows)
        body += (f"\n_ths: {n}/{n} rows, {time.time() - t0:.2f}s | "
                 f"THS K线（同花顺行情接口·{code_to_symbol(code)}）_")
        ok = True
    except Exception as e:
        ok, body = False, f"[ths ERR] THS K线降级失败: {e}"
    return ("历史K线", body, ok, time.time() - t0, "ths")
