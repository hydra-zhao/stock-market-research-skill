"""Unified stock data facade."""
from __future__ import annotations

from .registry import get_registry


def _get(capability: str, **params):
    return get_registry().route(capability, **params)


def get_stock_snapshot(code): return _get("stock_snapshot", code=code)
def get_daily_k(code, start=None, end=None, adjust=None, **kw): return _get("daily_k", code=code, start=start, end=end, adjust=adjust, **kw)
def get_weekly_k(code, start=None, end=None, **kw): return _get("weekly_k", code=code, start=start, end=end, **kw)
def get_monthly_k(code, start=None, end=None, **kw): return _get("monthly_k", code=code, start=start, end=end, **kw)
def get_swing_qfq_history(code, start=None, end=None, **kw):
    """experimental capability：调用方必须显式传 ``allow_experimental=True``。

    旧实现在此 ``setdefault("allow_experimental", True)``，把 registry 的显式
    opt-in 门禁在门面上变成默认开启——与 capabilities.yaml 的"调用方必须显式
    allow_experimental"声明矛盾，任何新调用方都会静默拿到 experimental 源。
    生产调用方（round1_v2 swing 精度层）本就显式传参，故此处不改变现有路由。
    """
    return _get("swing_qfq_history", code=code, start=start, end=end, **kw)
def get_market_daily_dump(date=None, start=None, end=None, **kw): return _get("market_daily_dump", date=date, start=start, end=end, **kw)
def get_limit_up_pool(date=None): return _get("limit_up_pool", date=date)
def get_limit_down_pool(date=None): return _get("limit_down_pool", date=date)
def get_limit_ladder(date=None): return _get("limit_ladder", date=date)
def get_hotrank(date=None): return _get("hotrank", date=date)
def get_anomaly(code=None, date=None): return _get("anomaly", code=code, date=date)
def get_lhb(code=None, date=None): return _get("lhb", code=code, date=date)
def get_financials(code, period=None, **kw): return _get("financials", code=code, period=period, **kw)
def get_valuation(code, date=None, **kw): return _get("valuation", code=code, date=date, **kw)
def get_index_quote(code, **kw): return _get("index_quote", code=code, **kw)
def get_index_members(code, **kw): return _get("index_members", code=code, **kw)
def get_sector_members(code, **kw): return _get("sector_members", code=code, **kw)
def get_etf_data(code, **kw): return _get("etf", code=code, **kw)
def get_sector_fundflow(date=None, **kw): return _get("sector_fundflow", date=date, **kw)
def get_futures_market(**kw): return _get("futures_market", **kw)
def get_futures_position(**kw): return _get("futures_position", **kw)
def get_research(**kw): return _get("research", **kw)
def get_risk_events(code, **kw): return _get("risk_events", code=code, **kw)
