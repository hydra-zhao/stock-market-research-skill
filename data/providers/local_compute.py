"""Deterministic, network-free calculations over normalized daily bars."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def technical_features(bars: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute stable indicators without inventing values for short samples."""
    rows = sorted((dict(x) for x in bars), key=lambda x: str(x.get("date") or ""))
    closes = [float(x["close"]) for x in rows if x.get("close") is not None]
    highs = [float(x["high"]) for x in rows if x.get("high") is not None]
    lows = [float(x["low"]) for x in rows if x.get("low") is not None]
    out: dict[str, Any] = {"observations": len(closes)}
    for n in (5, 10, 20, 60, 120, 250, 360):
        out[f"ma{n}"] = _mean(closes[-n:]) if len(closes) >= n else None
    for n in (5, 10, 20, 120, 250):
        out[f"return_{n}d"] = (
            (closes[-1] / closes[-n - 1] - 1) * 100 if len(closes) >= n + 1 and closes[-n - 1] else None
        )
    out["amplitude_20d"] = (
        (max(highs[-20:]) / min(lows[-20:]) - 1) * 100
        if len(highs) >= 20 and len(lows) >= 20 and min(lows[-20:]) else None
    )
    out["high_120d"] = max(highs[-120:]) if len(highs) >= 120 else None
    out["high_120d_space"] = (
        (out["high_120d"] / closes[-1] - 1) * 100
        if out["high_120d"] is not None and closes and closes[-1] else None
    )
    return out


def resample_bars(bars: Iterable[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """Aggregate daily OHLCV to calendar week or month, preserving no fake dates."""
    if period not in {"weekly", "monthly"}:
        raise ValueError("period must be weekly or monthly")
    from datetime import date
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in sorted((dict(x) for x in bars), key=lambda x: str(x.get("date") or "")):
        d = date.fromisoformat(str(raw["date"])[:10])
        key = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}" if period == "weekly" else f"{d.year}-{d.month:02d}"
        groups[key].append(raw)
    out = []
    for rows in groups.values():
        volume = sum(float(x.get("volume") or 0) for x in rows)
        turnover = sum(float(x.get("turnover") or 0) for x in rows)
        out.append({"date": rows[-1]["date"], "open": rows[0].get("open"),
                    "high": max(float(x["high"]) for x in rows if x.get("high") is not None),
                    "low": min(float(x["low"]) for x in rows if x.get("low") is not None),
                    "close": rows[-1].get("close"), "volume": volume, "turnover": turnover})
    return out


def swing_candidates(frame, names: dict[str, str], n: int = 50) -> list[dict[str, Any]]:
    """Existing POOL-017 coarse screen, moved intact to the reproducible local layer."""
    import pandas as pd

    if frame is None or frame.empty:
        return []
    df = frame.sort_values(["code", "date"]).copy()
    g = df.groupby("code", sort=False)
    df["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    df["ma20_p5"] = g["ma20"].shift(5)
    df["chg5"] = g["close_price"].pct_change(5) * 100
    df["chg20"] = g["close_price"].pct_change(20) * 100
    df["high120"] = g["high_price"].transform(lambda s: s.rolling(120).max())
    df["high20"] = g["high_price"].transform(lambda s: s.rolling(20).max())
    df["low20"] = g["low_price"].transform(lambda s: s.rolling(20).min())
    df["limitups_1y"] = g["is_zt"].transform(lambda s: s.rolling(243, min_periods=1).sum())
    weekly = df[["code", "date", "close_price"]].copy()
    weekly["week"] = pd.to_datetime(weekly["date"]).dt.to_period("W-FRI")
    weekly = weekly.groupby(["code", "week"], sort=False).tail(1)
    weekly["ma20w"] = weekly.groupby("code", sort=False)["close_price"].transform(
        lambda s: s.rolling(20).mean())
    last_week = weekly.groupby("code", sort=False).tail(1).set_index("code")["ma20w"]
    latest = df.groupby("code", sort=False).tail(1).copy()
    latest["ma20w"] = latest["code"].map(last_week)
    valid = latest[
        ~latest["is_st"]
        & ~latest["code"].str.startswith(("688", "689", "4", "8", "92"))
        & (latest["close_price"] > latest["ma20"])
        & (latest["ma20"] > latest["ma20_p5"])
        & (latest["close_price"] > latest["ma20w"])
        & latest["chg5"].between(-5, 15, inclusive="both")
        & (latest["chg20"] > 0)
        & (latest["turnover"] > 1_000_000_000)
    ].copy()
    valid["potential_upside"] = (valid["high120"] / valid["close_price"] - 1) * 100
    valid["amplitude20"] = (valid["high20"] / valid["low20"] - 1) * 100
    valid = valid.sort_values("potential_upside", ascending=False).head(int(n))
    out = []
    for _, row in valid.iterrows():
        out.append({"code": row["code"], "name": names.get(row["code"], ""),
                    "metrics": {"potential_upside": round(float(row["potential_upside"]), 4),
                                "close": round(float(row["close_price"]), 3),
                                "high120": round(float(row["high120"]), 3),
                                "amplitude20": round(float(row["amplitude20"]), 4),
                                "limitups_1y": int(row["limitups_1y"] or 0),
                                "float_mv": None, "turnover": float(row["turnover"]),
                                "chg5": round(float(row["chg5"]), 4),
                                "chg20": round(float(row["chg20"]), 4)}})
    return out
