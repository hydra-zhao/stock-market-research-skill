"""A/B provenance audit; same-family comparisons are never called independent."""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from providers.registry import ProviderRegistry
else:
    from .registry import ProviderRegistry


AUDIT_CAPABILITIES = ("index_quote", "daily_k", "market_daily_dump", "limit_up_pool",
                      "limit_down_pool", "limit_ladder", "financials", "lhb", "hotrank", "etf")


def audit_rows(registry: ProviderRegistry | None = None) -> list[dict]:
    reg = registry or ProviderRegistry()
    out = []
    for capability in AUDIT_CAPABILITIES:
        cfg = reg.config(capability)
        primary = cfg["primary"]
        legacy = (cfg.get("fallback") or [None])[0]
        cross = (cfg.get("crosscheck") or [legacy])[0]
        relation = reg.crosscheck_relation(primary, cross) if cross else "UNVERIFIED"
        families = reg.matrix.get("vendor_families", {})
        out.append({"capability": capability, "fuyao": "NOT_RUN", "legacy_source": legacy or "-",
                    "cross_source": cross or "-",
                    # vendor family 直接列出（SRC-010 的原始依据），不必靠
                    # same_vendor_family 布尔值反推"是不是同一家"
                    "family_primary": families.get(primary, "none"),
                    "family_cross": families.get(cross, "none") if cross else "-",
                    "difference": "-", "tolerance": "-",
                    "same_vendor_family": relation == "SAME_VENDOR_ONLY",
                    "result": "SAME_VENDOR_ONLY" if relation == "SAME_VENDOR_ONLY" else "UNVERIFIED"})
    return out


def render(items: list[dict]) -> str:
    keys = ["capability", "fuyao", "legacy_source", "cross_source", "family_primary", "family_cross", "difference", "tolerance", "same_vendor_family", "result"]
    lines = ["|" + "|".join(keys) + "|", "|" + "---|" * len(keys)]
    lines += ["|" + "|".join(str(x[k]) for k in keys) + "|" for x in items]
    lines.append("NOT_RUN/UNVERIFIED: no live request is made without explicit manual credentials and fixtures.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render(audit_rows()))
