"""Incremental bridge from legacy round1 task tuples to capability routing."""
from __future__ import annotations

import re

from .registry import data_mode
from .runner import task

_LABEL_CAPABILITY = {
    "涨停板": "limit_up_pool", "跌停板": "limit_down_pool", "炸板股": "limit_break_pool",
    "连板天梯": "limit_ladder", "历史涨跌停": "market_daily_dump",
    "历史成交额": "market_daily_dump", "历史K线": "daily_k", "周线技术": "weekly_k",
    "个股行情": "stock_snapshot", "财务速览": "financials", "龙虎榜": "lhb",
    "估值水位": "valuation", "国家队ETF": "etf", "板块资金": "sector_fundflow",
    "板块资金流入": "sector_fundflow", "板块资金流出": "sector_fundflow",
}


def route_tasks(tasks: list[tuple], scope: str = "") -> list[tuple]:
    """Keep tuple/output compatibility while moving source choice into the registry."""
    if data_mode() == "legacy":
        return tasks
    out = []
    for item in tasks:
        label, kind, query = item[:3]
        limit = item[3] if len(item) > 3 else 5
        capability = _LABEL_CAPABILITY.get(label)
        if not capability:
            out.append(item)
            continue
        params = {"query": query, "limit": limit, "legacy_kind": kind,
                  "skill_id": kind.split(":", 1)[1] if str(kind).startswith("iw:") else ""}
        if capability in {"daily_k", "weekly_k"}:
            match = re.search(r"\d{6}", str(query))
            if not match:
                out.append(item)
                continue
            # weekly_k 由日线本地重采样：days=limit 只会产出 1 根周线（旧问财口径
            # 是 limit 周且带周线 MA），按 1 周≈5 个交易日放大并保底 130 日
            # （≥21 周才够算 MA20 与其方向）。
            days = int(limit) if capability == "daily_k" else max(int(limit) * 5 + 15, 130)
            params.update({"code": match.group(0), "days": days})
        if capability == "market_daily_dump":
            params["metric"] = "amount" if label == "历史成交额" else "ztdt"
        out.append((label, "provider", task(capability, **params), limit))
    return out
