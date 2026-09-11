#!/usr/bin/env python3
"""case_lib.py — 腾讯日K取数函数（公开演示版精简 stub）。

生产版本模块是滚动的形态案例库（自动捕获/更新/相似度匹配），案例内容
与匹配口径属于私有策略知识，不在公开版提供。公开版仅保留其中的
**数据面函数** ``fetch_tencent_kline``（腾讯零配额前复权K线拉取），
供 ``providers/tencent_qfq.py`` 与形态匹配使用 —— 接口签名与生产版一致。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.netguard import http_get

HTTP_RETRIES = 3


def norm_symbol(code: str) -> str:
    """6位代码 → 腾讯带市场前缀符号（sh/sz/bj）。"""
    code = str(code).strip().lower()
    digits = code[-6:] if code.isdigit() or len(code) >= 6 else code
    if digits.startswith(("sh", "sz", "bj")):
        return digits
    if digits.startswith(("6", "9", "5")):
        return f"sh{digits}"
    if digits.startswith(("4", "8")):
        return f"bj{digits}"
    return f"sz{digits}"


def parse_kline_payload(payload: dict, symbol: str, period: str) -> list[dict]:
    """腾讯 fqkline 响应 → ``[{date, open, close, high, low, volume}, ...]``。"""
    node = ((payload or {}).get("data") or {}).get(symbol) or {}
    rows = node.get(period) or node.get(f"qfq{period}") or []
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            out.append({
                "date": str(row[0]),
                "open": float(row[1]), "close": float(row[2]),
                "high": float(row[3]), "low": float(row[4]),
                "volume": float(row[5]),
            })
        except (TypeError, ValueError):
            continue
    return out


def fetch_tencent_kline(code: str, period: str = "day", start: str = "", end: str = "",
                        count: int = 320, fetch_json=None, sleep_fn=time.sleep) -> list[dict]:
    """拉腾讯前复权 K 线；断连退避最多尝试3次，最终失败抛 RuntimeError。"""
    if period not in ("day", "week"):
        raise ValueError(f"period 只支持 day/week，收到: {period}")
    symbol = norm_symbol(code)
    fetch_json = fetch_json or (lambda url: json.loads(http_get(url, timeout=15).text))
    param = urllib.parse.quote(f"{symbol},{period},{start},{end},{count},qfq", safe=",|")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
    last_err = None
    for attempt in range(HTTP_RETRIES):
        try:
            return parse_kline_payload(fetch_json(url), symbol, period)
        except Exception as e:
            last_err = e
            if attempt < HTTP_RETRIES - 1:
                sleep_fn(0.5 * (2 ** attempt))
    raise RuntimeError(f"腾讯K线拉取失败 {symbol} {period}: {last_err}")
