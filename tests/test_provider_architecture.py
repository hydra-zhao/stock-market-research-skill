"""Hermetic contracts for the hybrid provider architecture."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))

from providers.base import Provider
from providers.compat import route_tasks
from providers.cache import cache_key
from providers.errors import DataStale, ProviderUnavailable, RateLimited, SchemaDrift
from providers.local_compute import resample_bars, swing_candidates, technical_features
from providers.models import DataResult, ProviderIdentity
from providers.registry import ProviderRegistry, data_mode, load_matrix


class FakeProvider(Provider):
    def __init__(self, name, family, outcome):
        self.identity = ProviderIdentity(name, family)
        self.outcome = outcome
        self.calls = 0

    def fetch(self, capability, **params):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return DataResult(self.outcome, self.identity.name, self.identity.family,
                          status="ok", capability=capability)


def matrix(primary="fuyao", fallback=None, family2="eastmoney_family"):
    return {"vendor_families": {"fuyao": "ths_family", "iwencai": "ths_family",
                                 "mx": family2},
            "capabilities": {"daily_k": {"primary": primary,
                                            "fallback": fallback or [], "cacheable": True}}}


def test_contract_and_fallback_provenance():
    first = FakeProvider("fuyao", "ths_family", ProviderUnavailable("no key"))
    second = FakeProvider("mx", "eastmoney_family", [{"close": 10}])
    reg = ProviderRegistry(matrix(fallback=["mx"]), {"fuyao": first, "mx": second}, "hybrid")
    got = reg.route("daily_k", code="000001")
    assert got.usable and got.status == "degraded"
    assert got.source == "mx" and got.provider_family == "eastmoney_family"
    assert got.fallback_from == "fuyao"
    assert got.metadata["route_failures"][0][1] == "unavailable"


def test_same_vendor_is_not_independent_crosscheck():
    reg = ProviderRegistry(load_matrix(), {}, "hybrid")
    assert reg.crosscheck_relation("fuyao", "iwencai") == "SAME_VENDOR_ONLY"
    assert reg.crosscheck_relation("fuyao", "ths_dataapi") == "SAME_VENDOR_ONLY"
    assert reg.crosscheck_relation("fuyao", "mx") == "CROSS_SOURCE"


def test_no_key_failure_is_typed_and_does_not_abort_registry():
    first = FakeProvider("fuyao", "ths_family", ProviderUnavailable("FUYAO_API_KEY 未设置"))
    second = FakeProvider("iwencai", "ths_family", ProviderUnavailable("IWENCAI_API_KEY 未设置"))
    reg = ProviderRegistry(matrix(fallback=["iwencai"]), {"fuyao": first, "iwencai": second}, "hybrid")
    got = reg.route("daily_k", code="000001")
    assert got.status == "unavailable" and got.value is None
    assert len(got.metadata["route_failures"]) == 2


def test_rate_limit_falls_back_and_is_observable():
    first = FakeProvider("fuyao", "ths_family", RateLimited("4001"))
    second = FakeProvider("mx", "eastmoney_family", [1])
    got = ProviderRegistry(matrix(fallback=["mx"]), {"fuyao": first, "mx": second}, "hybrid").route("daily_k")
    assert got.status == "degraded"
    assert got.metadata["route_failures"][0][1] == "rate_limited"


def test_stale_and_partial_cache_semantics_are_distinct():
    stale = FakeProvider("fuyao", "ths_family", DataStale("old trading day"))
    got = ProviderRegistry(matrix(), {"fuyao": stale}, "hybrid").route("daily_k")
    assert got.status == "stale"
    assert cache_key("fuyao", "daily_k", symbol="000001", partial=False) != cache_key(
        "fuyao", "daily_k", symbol="000001", partial=True)


def test_incomplete_value_is_not_usable_by_default():
    provider = FakeProvider("fuyao", "ths_family", [1])
    provider.fetch = lambda capability, **params: DataResult(
        [1], "fuyao", "ths_family", status="incomplete", capability=capability,
        metadata={"raw_status": "incomplete_intraday"})
    got = ProviderRegistry(matrix(), {"fuyao": provider}, "hybrid").route(
        "daily_k", include_today=True)
    assert not got.usable and got.status == "incomplete"
    assert got.metadata["raw_status"] == "incomplete_intraday"


def test_candidate_and_disabled_providers_are_mechanically_blocked():
    matrix_data = {
        "vendor_families": {"candidate": "ths_family", "disabled": "eastmoney_family",
                            "mx": "eastmoney_family"},
        "capabilities": {"daily_k": {
            "primary": "candidate", "fallback": ["disabled", "mx"],
            "candidate": ["candidate"], "disabled": ["disabled"],
        }},
    }
    candidate = FakeProvider("candidate", "ths_family", [{"close": 1}])
    disabled = FakeProvider("disabled", "eastmoney_family", [{"close": 2}])
    fallback = FakeProvider("mx", "eastmoney_family", [{"close": 3}])
    reg = ProviderRegistry(matrix_data,
                           {"candidate": candidate, "disabled": disabled, "mx": fallback},
                           "hybrid")
    got = reg.route("daily_k")
    assert got.usable and got.source == "mx"
    assert got.status == "degraded" and got.fallback_from == "candidate"
    assert candidate.calls == 0 and disabled.calls == 0 and fallback.calls == 1
    assert {row[0] for row in got.metadata["route_failures"]} == {"candidate", "disabled"}


def test_candidate_only_capability_fails_closed():
    matrix_data = {
        "vendor_families": {"fuyao": "ths_family"},
        "capabilities": {"daily_k": {
            "primary": "fuyao", "fallback": [], "candidate": ["fuyao"],
        }},
    }
    provider = FakeProvider("fuyao", "ths_family", [{"close": 1}])
    got = ProviderRegistry(matrix_data, {"fuyao": provider}, "hybrid").route("daily_k")
    assert got.value is None and got.status == "not_supported" and not got.usable
    assert provider.calls == 0


def test_two_schema_drifts_temporarily_disable_capability():
    bad = FakeProvider("fuyao", "ths_family", SchemaDrift("missing close"))
    good = FakeProvider("mx", "eastmoney_family", [1])
    reg = ProviderRegistry(matrix(fallback=["mx"]), {"fuyao": bad, "mx": good}, "hybrid")
    reg.route("daily_k", nonce=1)
    reg.route("daily_k", nonce=2)
    assert ("fuyao", "daily_k") in reg.disabled
    before = bad.calls
    reg.route("daily_k", nonce=3)
    assert bad.calls == before


def test_feature_flags_and_legacy_compat(monkeypatch):
    monkeypatch.delenv("STOCK_DATA_MODE", raising=False)
    assert data_mode() == "hybrid"
    legacy = [("历史K线", "iw:hithink-market-query", "000001 最近60日", 60)]
    assert route_tasks(legacy)[0][1] == "provider"
    monkeypatch.setenv("STOCK_DATA_MODE", "legacy")
    assert route_tasks(legacy) == legacy


def test_local_technicals_short_sample_and_resample():
    bars = [{"date": f"2026-01-{i:02d}", "open": i, "high": i + 1, "low": i - 1,
             "close": i, "volume": 100, "turnover": 1000} for i in range(1, 22)]
    feat = technical_features(bars)
    assert feat["ma20"] == pytest.approx(sum(range(2, 22)) / 20)
    assert feat["ma60"] is None
    assert feat["return_5d"] == pytest.approx((21 / 16 - 1) * 100)
    assert len(resample_bars(bars, "monthly")) == 1


def test_swing_local_computation_keeps_existing_market_exclusions():
    rows = []
    start = date(2025, 1, 1)
    for code in ("000001", "688001"):
        for i in range(160):
            px = 10 + i * 0.02
            rows.append({"code": code, "date": str(start + timedelta(days=i)),
                         "close_price": px, "high_price": px * 1.02,
                         "low_price": px * 0.98, "turnover": 1_500_000_000,
                         "is_st": False, "is_zt": i % 40 == 0})
    got = swing_candidates(pd.DataFrame(rows), {"000001": "平安银行", "688001": "科创"})
    assert [x["code"] for x in got] == ["000001"]


def test_capability_matrix_marks_risk_hard_gate_and_fuyao_supporting_only():
    cfg = load_matrix()["capabilities"]["risk_events"]
    assert cfg["hard_gate_relevant"] is True
    assert cfg["primary"] == "risk_official"
    assert cfg["supporting"] == ["fuyao"]


def test_unverified_fuyao_capabilities_are_disabled_candidates():
    matrix = load_matrix()
    reg = ProviderRegistry(matrix, {}, "hybrid")
    expected = {
        "financials": "iwencai", "valuation": "iwencai",
        "index_members": "iwencai", "sector_members": "iwencai",
        "stock_snapshot": "iwencai", "index_quote": "mx",
        "etf": "akshare_eastmoney",
    }
    for capability, active_primary in expected.items():
        cfg = matrix["capabilities"][capability]
        assert cfg["primary"] == active_primary
        assert cfg["candidate"] == ["fuyao"]
        assert cfg["disabled"] == ["fuyao"]
        assert "fuyao" not in reg.order(capability)
    assert matrix["capabilities"]["etf"]["crosscheck"] == ["iwencai"]


def test_stock_snapshot_primary_path_is_not_marked_degraded():
    # 回归锁定：fuyao 未实现的能力不得留在 primary（旧矩阵 stock_snapshot/index_quote
    # 仍指 fuyao → 每次先撞 NotSupported，成功取数被误标 degraded+fallback_from）。
    good = FakeProvider("iwencai", "ths_family", [{"close": 10}])
    reg = ProviderRegistry(load_matrix(), {"iwencai": good}, "hybrid")
    got = reg.route("stock_snapshot", code="000001")
    assert got.status == "ok" and got.fallback_from is None
    assert "route_failures" not in got.metadata


def test_compat_weekly_depth_and_daily_unchanged(monkeypatch):
    import json as _json
    monkeypatch.setenv("STOCK_DATA_MODE", "hybrid")
    tasks = route_tasks([
        ("周线技术", "hithink-market-query", "600519 周K线 周线MA20"),
        ("历史K线", "iw:hithink-market-query", "600519 最近60日", 60),
    ])
    weekly, daily = (_json.loads(t[2]) for t in tasks)
    assert weekly["capability"] == "weekly_k"
    assert weekly["params"]["days"] >= 130          # ≥21 周才够 MA20 与方向
    assert daily["params"]["days"] == 60            # 日线口径保持


def test_weekly_render_reports_ma_and_direction():
    from providers.runner import _render
    bars = [{"date": f"2026-W{i:02d}", "open": i, "high": i + 1, "low": i - 1,
             "close": i, "volume": 100, "turnover": 1000} for i in range(1, 26)]
    body = _render("weekly_k", bars, {})
    assert "20周均线方向: 上行" in body and "MA20=15.50" in body
    short = _render("weekly_k", bars[:8], {})
    assert "样本不足(需21周)" in short and "MA20=样本不足" in short


def test_weekly_monthly_provenance_records_daily_resample(monkeypatch):
    from providers.fuyao import FuyaoProvider

    monkeypatch.setenv("FUYAO_API_KEY", "fixture-key")
    provider = FuyaoProvider()
    monkeypatch.setattr(provider, "_fetch", lambda capability, **params: [
        {"date": "2026-09-04", "open": 10, "high": 11, "low": 9, "close": 10.5}
    ])
    for capability in ("weekly_k", "monthly_k"):
        got = provider.fetch(capability, code="000001")
        assert got.metadata["derived"] is True
        assert got.metadata["derived_from"] == {
            "capability": "daily_k", "source": "fuyao", "provider_family": "ths_family"
        }
        assert got.metadata["derivation"] == f"local_resample_{capability}"


def test_swing_qfq_provider_has_registry_owned_completeness_and_lineage(monkeypatch):
    from providers.tencent_qfq import TencentQfqProvider

    bars = [{"date": f"2026-01-{i:02d}", "open": 10, "close": 10.5,
             "high": 11, "low": 9, "volume": 100} for i in range(1, 6)]
    monkeypatch.setattr("case_lib.fetch_tencent_kline",
                        lambda *args, **kwargs: bars)
    provider = TencentQfqProvider()
    result = provider.fetch("swing_qfq_history", code="000001", count=5,
                            min_rows=5, cutoff="2026-01-05")
    assert result.usable and result.source == "tencent"
    assert result.provider_family == "tencent_family"
    assert result.metadata["lineage"] == "tencent_qfq_daily_k"
    assert result.metadata["cutoff"] == "2026-01-05"
    assert result.metadata["required_rows"] == 5

    incomplete = provider.fetch("swing_qfq_history", code="000001", count=5,
                                min_rows=120, cutoff="2026-01-05")
    assert incomplete.status == "incomplete" and not incomplete.usable


def test_fuyao_anomaly_cannot_clear_official_chain_failure(monkeypatch):
    from sources import risk_scan

    monkeypatch.setattr(risk_scan, "_fuyao_anomaly_hits",
                        lambda codes, today: {"000818": ("2026-01-01", "[fuyao异动] 立案", "🔴")})

    def em_boom(url, params):
        raise RuntimeError("eastmoney down")

    class CninfoBoom:
        @staticmethod
        def stock_zh_a_disclosure_report_cninfo(**kwargs):
            raise RuntimeError("cninfo down")

    _label, body, ok, _elapsed, _src = risk_scan.run_risk_scan(
        "000818", em=em_boom, cninfo=CninfoBoom())
    assert ok is False
    assert "风险无法核查" in body


def test_risk_provenance_does_not_promote_eastmoney_to_official(monkeypatch):
    from providers.risk_official import RiskOfficialProvider
    from sources import risk_scan

    monkeypatch.setattr(risk_scan, "scan_code", lambda code, **kwargs: ([], "东财"))
    em = RiskOfficialProvider().fetch("risk_events", code="000001")
    assert em.provider_family == "eastmoney_family"
    assert em.metadata["verification"] == "eastmoney_announcement"
    assert em.metadata["announcement_chain_verified"] is True
    assert em.metadata["official_chain_verified"] is False
    assert em.metadata["official_regulatory_verified"] is False

    monkeypatch.setattr(risk_scan, "scan_code", lambda code, **kwargs: ([], "巨潮"))
    official = RiskOfficialProvider().fetch("risk_events", code="000001")
    assert official.metadata["verification"] == "official_disclosure"
    assert official.metadata["official_chain_verified"] is True
    assert official.metadata["official_regulatory_verified"] is False


def test_audit_marks_same_family_comparison_honestly():
    from providers.audit import audit_rows

    rows = {x["capability"]: x for x in audit_rows(ProviderRegistry(load_matrix(), {}, "hybrid"))}
    assert rows["hotrank"]["result"] == "SAME_VENDOR_ONLY"
    assert rows["daily_k"]["result"] == "UNVERIFIED"


def test_experimental_gate_is_metadata_driven_not_name_hardcoded():
    """审计收口（G，2026-09-10）：experimental 门禁唯一事实源=capabilities.yaml。

    旧实现把门禁写成 `capability == "swing_qfq_history"`：新增/改名 experimental
    能力时门禁静默失效，审计也读不出"谁被 experimental 挡着"。
    """
    reg = ProviderRegistry(load_matrix(), {}, "hybrid")

    assert reg.experimental_providers("swing_qfq_history") == {"tencent"}
    assert reg.experimental_providers("pattern_history") == {"tencent"}
    # 未声明的能力=无门禁（不能凭空把别家源当 experimental 挡掉）
    assert reg.experimental_providers("daily_k") == set()

    # 默认：experimental provider 不进路由；显式 opt-in 才参与
    assert reg.order("swing_qfq_history") == []
    assert reg.order("swing_qfq_history", allow_experimental=True) == ["tencent"]

    # pattern_history 的 primary 是生产源(iwencai)，experimental 只在 crosscheck
    # ——不得因为能力级 status=experimental 就把生产主源一起挡掉
    assert reg.order("pattern_history") == ["iwencai"]
    default = reg.route("pattern_history", code="600000")
    assert "iwencai" in (default.metadata.get("active_order") or []) or \
        default.status != "not_supported"
    assert default.metadata.get("raw_status") != "experimental_blocked"


def test_experimental_primary_is_fail_closed_and_new_capability_gets_gate():
    """primary 即 experimental 源且未 opt-in → 整条能力不可用（不静默换源）。

    同一门禁对新能力自动生效（此处临时登记一个新能力验证，无需改 registry.py）。
    """
    matrix = load_matrix()
    matrix["capabilities"]["brand_new_hist"] = {
        "primary": "tencent", "fallback": ["iwencai"],
        "status": "experimental", "experimental_providers": ["tencent"]}
    reg = ProviderRegistry(matrix, {}, "hybrid")
    blocked = reg.route("brand_new_hist", code="600000")
    assert blocked.status == "not_supported"
    assert blocked.metadata["raw_status"] == "experimental_blocked"
    assert blocked.metadata["active_order"] == []
    # 显式 opt-in 后按正常优先级路由（此处 iwencai 未注册 → 记为失败原因）
    allowed = reg.route("brand_new_hist", code="600000", allow_experimental=True)
    assert allowed.metadata["raw_status"] != "experimental_blocked"


def test_provider_facade_does_not_silently_opt_into_experimental():
    """门面不得替调用方开 experimental 门（旧 get_swing_qfq_history 的 setdefault）。"""
    import inspect

    import providers

    src = inspect.getsource(providers.get_swing_qfq_history)
    body = src.split('"""')[-1]  # 只看函数体：docstring 会引用旧实现，不算违规
    assert "setdefault" not in body and "allow_experimental" not in body
    got = providers.get_swing_qfq_history("600000")
    assert got.status == "not_supported"
    assert got.metadata["raw_status"] == "experimental_blocked"


def test_health_surfaces_governance_state():
    """provider 治理状态可审计：disabled / experimental 必须能从 health 读出。"""
    from providers.health import rows

    by = {x["provider"]: x for x in rows(ProviderRegistry(load_matrix(), {}, "hybrid"))}
    assert by["tencent"]["experimental"] is True
    assert by["tencent"]["capabilities"] == 1
    assert by["iwencai"]["experimental"] is False


def test_route_counts_match_documented_numbers():
    """data-sources.md 的路数声明必须与 builders 一致（本次审计修 15+8 → 15+9）。"""
    import builders

    market = builders.build_market()
    quick = builders.build_market_quick()
    core = builders.build_market_core()
    stock = builders.build_quick_complete()

    def kinds(tasks):
        out = {}
        for _label, kind, *_rest in tasks:
            out[kind.split(":")[0]] = out.get(kind.split(":")[0], 0) + 1
        return out

    assert len(market) == 21 and kinds(market) == {"iw": 17, "mx": 3, "ak": 1}
    assert len(quick) == 15 and kinds(quick) == {"iw": 13, "mx": 2}
    assert len(core) == 9 and kinds(core) == {"iw": 8, "ak": 1}
    assert len(stock) == 18  # quick 15 + core 独有 3
    # core 不得经 MARKET_IWENCAI 二次定义（A2 修复的不变式，此处锁路数同源）
    assert {t[0] for t in quick} & {"板块资金"} and \
        {t[0] for t in core if t[0] == "板块资金流出"}
