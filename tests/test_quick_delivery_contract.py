import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
if str(DATA) not in sys.path:
    sys.path.insert(0, str(DATA))


def _context():
    from quick_contract import stage
    now = datetime(2026, 9, 10, 16, 40)
    return {
        "schema_version": "1.0", "artifact_type": "quick_context",
        "generated_at": now.isoformat(), "data_date": "2026-09-10",
        "source_snapshot": {"path": "raw.md", "sha256": "0" * 64, "deliverable": False},
        "market": {"limit_up": 34, "limit_down": 11, "bomb": 22, "max_ladder": 4,
                   "breadth_up": 955, "breadth_down": 4512, "turnover": 16468.7,
                   "index_close": 3934.4, "index_change_pct": -0.43},
        "eco": {"state": "ice", "label": "🔴 冰点期", "relay_allowed": False,
                "verdicts": {"tuishen": "🔴", "niepan": "🔴", "yangjia": "🟡", "jianguqiyi": "⚪"}},
        "holdings": [{"code": "002714", "name": "牧原股份", "track": "长线底仓", "cost": "43.86", "status": "持有", "source": "fixture"}],
        "leaders": [],
        "relay_analysis": {"max_ladder": 4, "previous_top": {"code": None, "name": None,
                            "previous_boards": None, "current_change_pct": None, "status": None},
                           "advancement_rate": None, "prior_limit_premium": None,
                           "broken_count": 0, "big_loss_count": 0, "big_loss_threshold_pct": -7.0,
                           "high_board_survival": {"previous_high_count": None, "survived_count": None},
                           "state": "unverified", "reasons": [], "interpretation": "接力关键事实不完整，状态未验证。"},
        "mainline_analysis": {"themes": [], "confirmed_mainline": None,
                              "summary": "首板题材结构未验证，主线不作确认。"},
        "tomorrow_plan": {"can_trade_if": [], "stay_out_if": ["主线仍未确认。"],
                          "watch_focus": [], "holding_focus": ["按长线底仓管理。"]},
        "actions": {
            "ultra_relay": {"allowed": False, "max_new_position_pct": 0, "note": "不开仓"},
            "swing": {"allowed": False, "max_new_position_pct": 0, "note": "观察"},
            "existing_longterm": {"allowed": True, "max_new_position_pct": 0, "note": "持有"},
        },
        "stages": {"collect": stage("collect", "complete", now, data_date="2026-09-10"),
                   "swing": stage("swing", "complete", now, data_date="2026-09-10"),
                   "us_etf": stage("us_etf", "complete", now, data_date="2026-09-10"),
                   "national_etf": stage("national_etf", "complete", now, data_date="2026-09-10"),
                   "seat": stage("seat", "preliminary", now, data_date="2026-09-10")},
        "hooks": {"seat": stage("seat", "preliminary", now, data_date="2026-09-10"),
                  "case": stage("case", "complete", now, data_date="2026-09-10"),
                  "leaders": stage("leaders", "complete", now, data_date="2026-09-10"),
                  "trendscan": stage("trendscan", "complete", now, data_date="2026-09-10"),
                  "wave": stage("wave", "complete", now, data_date="2026-09-10")},
        "sections": {"futures": "**中信期货 期指持仓变化 2026-09-10**", "national_etf": "数据日期：20260909",
                     "futures_facts": {
                         "label": "中信期货 期指持仓变化 2026-09-10", "as_of": "2026-09-10",
                         "citic_net_position": -77459, "citic_net_short": 77459,
                         "citic_long_change": 4802, "citic_short_change": 4354,
                         "citic_net_change": 448, "top15_net_change": -2919,
                         "top15_long_change": 11422, "top15_short_change": 14341,
                         "unverified_fields": []},
                     "ladder": [], "broken_boards": [], "broken_boards_unverified": [],
                     "first_board": "首板题材归类：无确认主线",
                     "swing": "## 趋势波段候选\n无合格标的", "us_etf": "## 美股指数ETF\nQQQ/SPY 已验证",
                     # 🆕 审计收口（D）：解析完整性账（schema required）
                     "table_parse": {"parsed": {"ladder": 0, "previous": 0,
                                                "current_up": 0, "holdings": 1},
                                     "malformed_counts": {"ladder": 0, "previous": 0,
                                                          "current_up": 0, "holdings": 0},
                                     "malformed": []}},
    }


def test_renderer_rejects_snapshot():
    from quick_renderer import render
    try:
        render({"artifact_type": "quick_snapshot"})
    except ValueError:
        pass
    else:
        raise AssertionError("snapshot must not be renderable")


def test_structural_lint_rejects_futures_holding_false_positive():
    from lint_review import lint_delivery
    errors = lint_delivery("## 聪明资金\n期指持仓正常\n")
    assert any("持仓对照" in e for e in errors)


def test_renderer_and_lint_pass():
    from lint_review import lint_delivery
    from quick_renderer import render
    context = _context()
    assert lint_delivery(render(context), context) == []


def test_preliminary_time_legality():
    from quick_contract import stage_temporal_valid
    assert stage_temporal_valid("seat", "preliminary", datetime(2026, 9, 10, 16, 59), data_date="2026-09-10")
    assert not stage_temporal_valid("seat", "preliminary", datetime(2026, 9, 10, 17, 0), data_date="2026-09-10")


def test_reused_requires_source_time():
    from quick_context import validate_context
    context = _context()
    context["stages"]["swing"]["status"] = "reused"
    context["stages"]["swing"]["source_time"] = None
    assert any("reused without source_time" in e for e in validate_context(context))


def test_action_conflict_rejected():
    from quick_context import validate_context
    context = _context()
    context["actions"]["ultra_relay"]["max_new_position_pct"] = 10
    assert any("action ultra_relay" in e for e in validate_context(context))


def test_artifact_change_invalidates_manifest(tmp_path):
    from quick_contract import atomic_write_json, sha256_file
    from quick_delivery import verify_delivery
    context = tmp_path / "context.json"
    artifact = tmp_path / "review.md"
    context.write_text("{}", encoding="utf-8")
    artifact.write_text("ok", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    atomic_write_json(manifest, {"context_path": str(context), "context_sha256": sha256_file(context),
                                 "artifact_path": str(artifact), "artifact_sha256": sha256_file(artifact),
                                 "lint_exit_code": 0, "publishable": True})
    assert verify_delivery(manifest) == []
    artifact.write_text("tampered", encoding="utf-8")
    assert any("TOCTOU" in e for e in verify_delivery(manifest))


def test_manifest_publishable_is_validator_result(tmp_path):
    from quick_contract import atomic_write_json, sha256_file
    from quick_delivery import verify_delivery
    c = tmp_path / "c"; a = tmp_path / "a"; m = tmp_path / "m.json"
    c.write_text("{}", encoding="utf-8"); a.write_text("x", encoding="utf-8")
    atomic_write_json(m, {"context_path": str(c), "context_sha256": sha256_file(c),
                          "artifact_path": str(a), "artifact_sha256": sha256_file(a),
                          "lint_exit_code": 1, "publishable": True})
    assert "lint failed" in verify_delivery(m)


FUTURES_FIXTURE = """**中信期货 期指持仓变化 2026-09-10**（盘后上传 → akshare）

| 品种 | 多头持仓 | 空头持仓 | 净持仓 | 多chg | 空chg | 净多chg | 信号 |
|------|------|------|------|------|------|------|------|
| **沪深300期货** | 32,304 | 53,979 | -21,675 | +2,166 | +2,281 | -115 | 🟢加空(建仓) +加多 |
| **合计** | 148,714 | 226,173 | -77,459 | +4,802 | +4,354 | +448 | |

**中信 vs 头部机构共识**（Top 15 统计，共 15 家有效）：
- Top 15 合计：净多chg=-2,919 · 多chg=+11,422 · 空chg=+14,341
"""


def test_futures_facts_parsed_from_real_snapshot():
    from quick_context import build_context
    snapshot = ROOT / "output" / "reviews" / "quick-snapshot-20260910-165315.md"
    if not snapshot.exists():
        return
    context = build_context(snapshot, now=datetime.fromisoformat("2026-09-10T17:05:00+08:00"))
    facts = context["sections"]["futures_facts"]
    assert facts["label"] == "中信期货 期指持仓变化 2026-09-10"
    assert facts["as_of"] == "2026-09-10"
    assert facts["citic_net_position"] == -77459
    assert facts["citic_net_short"] == 77459
    assert facts["citic_long_change"] == 4802
    assert facts["citic_short_change"] == 4354
    assert facts["citic_net_change"] == 448
    assert facts["top15_net_change"] == -2919
    assert facts["unverified_fields"] == []


def test_rendered_review_contains_futures_numbers():
    """N1 回归：最终交付正文必须出现期指核心数字（旧版只剩标题）。"""
    from quick_context import build_context
    from quick_renderer import render
    snapshot = ROOT / "output" / "reviews" / "quick-snapshot-20260910-165315.md"
    if not snapshot.exists():
        return
    markdown = render(build_context(snapshot, now=datetime.fromisoformat("2026-09-10T17:05:00+08:00")))
    futures_line = next(x for x in markdown.splitlines() if x.startswith("- 期指："))
    assert "中信净空 77,459 手" in futures_line
    assert "净多chg +448" in futures_line
    assert "多chg +4,802" in futures_line
    assert "空chg +4,354" in futures_line
    assert "Top15 净多chg -2,919" in futures_line


def test_futures_facts_partial_marks_unverified_fields():
    """缺 Top15 汇总行 → 三个 top15 字段为 null 且显式列入未验证；不得静默省略。"""
    from quick_context import parse_futures_facts
    block = FUTURES_FIXTURE.split("**中信 vs 头部机构共识**")[0]
    facts = parse_futures_facts(block)
    assert facts["citic_net_short"] == 77459
    assert facts["top15_net_change"] is None
    assert facts["top15_long_change"] is None
    assert facts["top15_short_change"] is None
    assert set(facts["unverified_fields"]) == {
        "top15_net_change", "top15_long_change", "top15_short_change"}


def test_futures_facts_empty_section_is_all_unverified():
    from quick_context import FUTURES_FACT_FIELDS, parse_futures_facts
    from quick_renderer import render
    facts = parse_futures_facts("")
    assert facts["label"] is None and facts["citic_net_short"] is None
    assert set(facts["unverified_fields"]) == set(FUTURES_FACT_FIELDS)
    text = render(_context_with_sections(futures_facts=facts))
    line = next(x for x in text.splitlines() if x.startswith("- 期指："))
    assert "未验证" in line and "未采集" in line


def test_futures_facts_bad_cells_do_not_default_to_zero():
    """合计行数字列坏掉 → null + 未验证，绝不写成 0。"""
    from quick_context import parse_futures_facts
    block = FUTURES_FIXTURE.replace("| -77,459 |", "| -- |").replace("| +4,802 |", "| 停牌 |")
    facts = parse_futures_facts(block)
    assert facts["citic_net_position"] is None
    assert facts["citic_long_change"] is None
    assert facts["citic_short_change"] == 4354
    assert "citic_net_position" in facts["unverified_fields"]
    assert "unverified_fields" not in facts["unverified_fields"]


def _context_with_sections(**overrides):
    context = _context()
    context["sections"].update(overrides)
    return context


def test_broken_boards_missing_change_column_is_not_a_break():
    """N2 反例①：涨跌幅列整列缺失 → 不进断板名单，进未验证。"""
    from quick_context import classify_broken_boards
    rows = [{"股票代码": "000523.SZ", "股票简称": "红棉股份", "连续涨停天数[20260909]": "2.0"}]
    broken, unverified = classify_broken_boards(rows)
    assert broken == []
    assert unverified[0]["name"] == "红棉股份"
    assert unverified[0]["reason"] == "change_pct_unverified"


def test_broken_boards_unparseable_cells_are_unverified():
    """N2 反例②③④：`--` / 空串与 None / 非法字符串一律不判断板。"""
    from quick_context import classify_broken_boards
    rows = [
        {"股票代码": "000001.SZ", "股票简称": "A", "连续涨停天数[20260909]": "2.0", "涨跌幅[20260910]": "--"},
        {"股票代码": "000002.SZ", "股票简称": "B", "连续涨停天数[20260909]": "2.0", "涨跌幅[20260910]": ""},
        {"股票代码": "000003.SZ", "股票简称": "C", "连续涨停天数[20260909]": "2.0", "涨跌幅[20260910]": None},
        {"股票代码": "000004.SZ", "股票简称": "D", "连续涨停天数[20260909]": "2.0", "涨跌幅[20260910]": "停牌"},
    ]
    broken, unverified = classify_broken_boards(rows)
    assert broken == []
    assert [x["name"] for x in unverified] == ["A", "B", "C", "D"]


def test_broken_boards_valid_below_threshold_still_breaks():
    """N2 正例：有效数值 <9.5 仍正常进断板名单（阈值未动）。"""
    from quick_context import classify_broken_boards
    rows = [
        {"股票代码": "000523.SZ", "股票简称": "红棉股份", "连续涨停天数[20260909]": "2.0",
         "涨跌幅[20260910]": "2.293578"},
        {"股票代码": "000978.SZ", "股票简称": "桂林旅游", "连续涨停天数[20260909]": "3.0",
         "涨跌幅[20260910]": "9.988648999999999"},
    ]
    broken, unverified = classify_broken_boards(rows)
    assert [x["name"] for x in broken] == ["红棉股份"]
    assert broken[0]["change_pct"] == 2.293578
    assert unverified == []


def test_unverified_boards_render_as_unverified_not_bomb():
    """N2 交付面：未验证行不得渲染成"+0.00%"断板；龙头不得被写成炸板。"""
    from quick_renderer import render
    context = _context_with_sections(
        broken_boards=[],
        broken_boards_unverified=[{"code": "000523", "name": "红棉股份",
                                   "previous_boards": "2.0", "reason": "change_pct_unverified"}])
    text = render(context)
    assert "未验证（不判断板）" in text
    assert "红棉股份（昨2.0板，涨跌幅未验证）" in text
    assert "+0.00%" not in text


def test_actual_snapshot_uses_turnover_section_not_limit_counts():
    from quick_context import build_context
    snapshot = ROOT / "output" / "reviews" / "quick-snapshot-20260910-165315.md"
    if not snapshot.exists():
        return
    context = build_context(snapshot, now=datetime.fromisoformat("2026-09-10T17:05:00+08:00"))
    assert context["market"]["turnover"] == 16468.7
    assert context["market"]["limit_up"] == 34


def test_preliminary_after_cutoff_blocks_delivery_gate():
    from quick_delivery import _critical_stage_errors
    context = _context()
    assert "hook seat temporal invalid" in _critical_stage_errors(
        context, now=datetime(2026, 9, 10, 17, 0))


def test_noncritical_failed_stage_can_degrade():
    from quick_delivery import _critical_stage_errors
    context = _context()
    context["stages"]["swing"]["status"] = "failed"
    assert _critical_stage_errors(context, now=datetime(2026, 9, 10, 16, 50)) == []


def test_preliminary_inside_window_can_publish():
    from quick_delivery import _critical_stage_errors
    assert _critical_stage_errors(_context(), now=datetime(2026, 9, 10, 16, 50)) == []


def test_delivery_lint_rejects_missing_and_empty_sections():
    from lint_review import lint_delivery
    missing = lint_delivery("## 核心数据\n涨停 1\n")
    assert any("missing H2 section: 持仓对照" in item for item in missing)
    empty = lint_delivery("## 持仓对照\n\n## 核心数据\n涨停 1\n")
    assert any("empty H2 section: 持仓对照" in item for item in empty)


def test_schema_rejects_unknown_context_property():
    from quick_context import validate_context
    context = _context()
    context["agent_guess"] = 34
    assert any("unexpected agent_guess" in item for item in validate_context(context))


def test_atomic_write_leaves_no_temp_file(tmp_path):
    from quick_contract import atomic_write_text
    target = tmp_path / "artifact.md"
    atomic_write_text(target, "complete")
    assert target.read_text(encoding="utf-8") == "complete"
    assert list(tmp_path.glob("*.tmp")) == []


# ---------- N4：FINAL-001 原样承载 seat_profile 状态，不折叠、按策略放行/阻断 ----------

def test_seat_status_passed_through_verbatim(tmp_path):
    """context 层不得把 incomplete/suspicious/repaired 等折叠成 unverified。"""
    import json

    from quick_context import _seat_status
    seats = tmp_path / "output" / "seats"
    seats.mkdir(parents=True)
    for status in ("complete", "repaired", "incomplete", "suspicious",
                   "failed_to_repair", "legacy_unverified", "future_unknown_state"):
        (seats / "20260910.status").write_text(
            json.dumps({"status": status, "checked_at": "2026-09-10T17:01:23+08:00"}),
            encoding="utf-8")
        assert _seat_status("2026-09-10", tmp_path) == (status, "2026-09-10T17:01:23+08:00")


def test_seat_policy_table_is_the_single_source():
    from quick_contract import seat_label, seat_policy
    assert seat_policy("complete") == "allow"
    assert seat_policy("repaired") == "allow"
    assert seat_policy("preliminary") == "window"
    assert seat_policy("incomplete") == "block"
    assert seat_policy("suspicious") == "block"
    assert seat_policy("failed_to_repair") == "block"
    assert seat_policy("legacy_unverified") == "allow_labeled"
    assert seat_policy("never_seen_before") == "block"
    assert seat_label("incomplete") == "不完整（交易所缺口/关键字段异常，需重拉全量）"


def test_seat_defect_states_block_publish_explicitly():
    from quick_delivery import _critical_stage_errors
    now = datetime(2026, 9, 10, 16, 50)
    for status in ("incomplete", "suspicious", "failed_to_repair", "failed"):
        context = _context()
        context["stages"]["seat"]["status"] = status
        assert _critical_stage_errors(context, now=now) == [
            f"seat stage status={status} blocked by policy"]
    # 未知状态：schema 层已拒绝（不在词表内），闸门仍按 fail-closed 双重拦截。
    unknown = _context()
    unknown["stages"]["seat"]["status"] = "future_unknown_state"
    unknown_errors = _critical_stage_errors(unknown, now=now)
    assert "stage seat temporal invalid" in unknown_errors
    assert "seat stage status=future_unknown_state blocked by policy" in unknown_errors
    for status in ("complete", "repaired", "unverified", "legacy_unverified", "preliminary"):
        context = _context()
        context["stages"]["seat"]["status"] = status
        assert _critical_stage_errors(context, now=now) == []


def test_seat_raw_status_is_rendered_with_its_label():
    from quick_context import validate_context
    from quick_renderer import render
    for status, label in (("incomplete", "不完整（交易所缺口/关键字段异常，需重拉全量）"),
                          ("repaired", "已修复（重拉后正式校验通过）"),
                          ("legacy_unverified", "历史未验证（无席位事实，需 audit --repair）")):
        context = _context()
        context["stages"]["seat"]["status"] = status
        assert validate_context(context) == []
        text = render(context)
        assert f"seat: {status}，" in text
        assert label in text


def test_manifest_records_schema_and_renderer_revision(tmp_path, monkeypatch):
    import json

    from quick_contract import RENDERER_VERSION, SCHEMA_REVISION
    manifest_path = _build_preliminary_delivery(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # 🆕 v7.3.5 1.1→1.2：market 派生指标 + holding.quote + swing_summary（交付层增强）
    assert SCHEMA_REVISION == "1.3" and RENDERER_VERSION == "1.3"
    assert manifest["schema_revision"] == "1.3"
    assert manifest["renderer_version"] == "1.3"
    # schema 主版本语义不变
    assert _context()["schema_version"] == "1.0"


# ---------- N8：reused 必须证明来源，且正文必须写明"本轮失败 + 复用自哪一刻" ----------

def test_reused_stage_without_verifiable_source_blocks_publish(tmp_path):
    from quick_contract import sha256_file
    from quick_delivery import _critical_stage_errors
    now = datetime(2026, 9, 10, 16, 50)
    context = _context()
    context["stages"]["swing"].update({"status": "reused",
                                       "source_time": "2026-09-10T16:34:51+08:00"})
    assert _critical_stage_errors(context, now=now) == ["stage swing reused source file missing"]

    older = tmp_path / "quick-snapshot-20260910-163451.md"
    older.write_text("## 趋势波段候选\n无合格标的\n", encoding="utf-8")
    context["stages"]["swing"]["source_path"] = str(older)
    context["stages"]["swing"]["source_sha256"] = "0" * 64
    assert _critical_stage_errors(context, now=now) == ["stage swing reused source hash mismatch"]

    context["stages"]["swing"]["source_sha256"] = sha256_file(older)
    assert _critical_stage_errors(context, now=now) == []


REAL_20260910_SWING_FAILURE = """## 📈 趋势波段候选（3-20交易日）

⚠️ 扫描失败，候选未验证（不是无候选）：OSError: [Errno 22] Invalid argument
"""

REAL_20260910_US_ETF_FAILURE = "⚠️ 月度/美股ETF观察附录失败（未静默）：OSError: [Errno 22] Invalid argument\n"


def test_real_20260910_oserror_reuse_is_parsed_with_source_proof(tmp_path):
    """真实 20260910 16:53:15 snapshot 的失败文本 → reused + OSError + 来源 hash。"""
    from quick_context import _appendix
    from quick_contract import sha256_file
    reviews = tmp_path / "output" / "reviews"
    reviews.mkdir(parents=True)
    good = reviews / "quick-snapshot-20260910-163451.md"
    good.write_text("## 📈 趋势波段候选（3-20交易日）\n\n无合格标的\n\n"
                    "## 美股指数ETF\nQQQ/SPY 已验证\n", encoding="utf-8")
    raw = REAL_20260910_SWING_FAILURE + "\n" + REAL_20260910_US_ETF_FAILURE
    failed = reviews / "quick-snapshot-20260910-165315.md"
    failed.write_text(raw, encoding="utf-8")

    swing = _appendix(failed, raw, "趋势波段候选", tmp_path, "2026-09-10")
    assert swing["status"] == "reused"
    assert swing["error"]["type"] == "OSError"
    assert swing["error"]["message"] == "[Errno 22] Invalid argument"
    assert swing["source_path"] == str(good.resolve())
    assert swing["source_sha256"] == sha256_file(good)

    us_etf = _appendix(failed, raw, "美股指数ETF", tmp_path, "2026-09-10")
    assert us_etf["status"] == "reused"
    assert us_etf["error"]["type"] == "OSError"
    assert us_etf["source_sha256"] == sha256_file(good)


SWING_OK_BLOCK = ("## 📈 趋势波段候选（3-20交易日）\n\n无合格标的（清洁）\n\n"
                  "## 美股指数ETF\nQQQ/SPY 已验证\n")
SWING_FAIL_BODY = (REAL_20260910_SWING_FAILURE + "\n" + REAL_20260910_US_ETF_FAILURE)


def _reviews_dir(tmp_path, names_and_bodies):
    reviews = tmp_path / "output" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    made = {}
    for name, body in names_and_bodies:
        path = reviews / name
        path.write_text(body, encoding="utf-8")
        made[name] = path
    return reviews, made


def _swing_appendix(path, raw, root):
    from quick_context import _appendix
    return _appendix(path, raw, "趋势波段候选", root, "2026-09-10")


def test_r1_reuses_nearest_earlier_success_never_future(tmp_path):
    """A：16:53 失败 + 16:34 成功 + 19:40 成功 → 必须复用 16:34，绝不能是 19:40。"""
    from quick_contract import sha256_file
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260910-163451.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-194019.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-165315.md", SWING_FAIL_BODY),
    ])
    current = made["quick-snapshot-20260910-165315.md"]
    got = _swing_appendix(current, SWING_FAIL_BODY, tmp_path)
    assert got["status"] == "reused"
    assert got["source_path"] == str(made["quick-snapshot-20260910-163451.md"].resolve())
    assert got["source_time"] == "2026-09-10T16:34:51+08:00"
    assert got["source_sha256"] == sha256_file(made["quick-snapshot-20260910-163451.md"])
    assert "194019" not in got["source_path"]


def test_r1_only_future_success_is_not_reused(tmp_path):
    """B：16:53 失败 + 19:40 成功 → 不得 reused（保持 failed，且不指向未来文件）。"""
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260910-194019.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-165315.md", SWING_FAIL_BODY),
    ])
    current = made["quick-snapshot-20260910-165315.md"]
    got = _swing_appendix(current, SWING_FAIL_BODY, tmp_path)
    assert got["status"] == "failed"
    assert got["source_path"] == str(current.resolve())
    assert "194019" not in got["source_path"]


def test_r1_picks_the_closest_earlier_success(tmp_path):
    """C：16:20 + 16:34 两个更早成功 → 必须选 16:34（最近）。"""
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260910-162000.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-163451.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-165315.md", SWING_FAIL_BODY),
    ])
    current = made["quick-snapshot-20260910-165315.md"]
    assert Path(_swing_appendix(current, SWING_FAIL_BODY, tmp_path)["source_path"]).name == \
        "quick-snapshot-20260910-163451.md"


def test_r1_current_success_never_enters_reuse_search(tmp_path):
    """D：当前快照自身成功 → complete，不进入 reused 搜索。"""
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260910-163451.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-165315.md", SWING_OK_BLOCK),
    ])
    current = made["quick-snapshot-20260910-165315.md"]
    got = _swing_appendix(current, SWING_OK_BLOCK, tmp_path)
    assert got["status"] == "complete"
    assert got["source_path"] == str(current.resolve())


def test_r1_cross_day_and_equal_time_candidates_are_excluded(tmp_path):
    """E + 边界：跨日成功快照、同刻副本、无法解析名字一律不得作为 reused 来源。"""
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260909-235959.md", SWING_OK_BLOCK),          # 跨日
        ("quick-snapshot-20260910-165315-copy.md", SWING_OK_BLOCK),     # 同一时刻
        ("quick-snapshot-20260910-badname.md", SWING_OK_BLOCK),         # 名字不可解析
        ("quick-snapshot-20260910-165315.md", SWING_FAIL_BODY),
    ])
    current = made["quick-snapshot-20260910-165315.md"]
    got = _swing_appendix(current, SWING_FAIL_BODY, tmp_path)
    assert got["status"] == "failed"
    assert got["source_path"] == str(current.resolve())


def test_r1_unparseable_current_snapshot_name_disables_reuse(tmp_path):
    """当前快照名不可解析 → 无法建立因果序，fail-closed 不复用任何文件。"""
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260910-163451.md", SWING_OK_BLOCK),
        ("quick-snapshot-20260910-badname.md", SWING_FAIL_BODY),
    ])
    current = made["quick-snapshot-20260910-badname.md"]
    got = _swing_appendix(current, SWING_FAIL_BODY, tmp_path)
    assert got["status"] == "failed"
    assert got["source_path"] == str(current.resolve())


def test_r1_us_etf_follows_the_same_causal_rule(tmp_path):
    """美股ETF段（走 ⚠️ 附录失败 回退正则）同样受时间因果约束。"""
    _, made = _reviews_dir(tmp_path, [
        ("quick-snapshot-20260910-194019.md", SWING_OK_BLOCK),
    ])
    reviews = tmp_path / "output" / "reviews"
    current = reviews / "quick-snapshot-20260910-165315.md"
    current.write_text(SWING_FAIL_BODY, encoding="utf-8")
    from quick_context import _appendix
    got = _appendix(current, SWING_FAIL_BODY, "美股指数ETF", tmp_path, "2026-09-10")
    assert got["status"] == "failed" and got["error"]["type"] == "OSError"
    assert got["source_path"] == str(current.resolve())


def test_r1_real_20260910_replay_no_longer_crosses_into_the_future():
    """真实 20260910 回放：16:53 只能引用更早的成功快照，不得再穿越到 19:40/19:55。"""
    from quick_context import _snapshot_datetime
    reviews = ROOT / "output" / "reviews"
    current = reviews / "quick-snapshot-20260910-165315.md"
    if not current.exists():
        return
    raw = current.read_text(encoding="utf-8", errors="replace")
    got = _swing_appendix(current, raw, ROOT)
    if got["status"] != "reused":
        return  # 真实目录已无更早成功快照时不构成本回归
    source = Path(got["source_path"])
    assert _snapshot_datetime(source) < _snapshot_datetime(current)
    assert "194019" not in source.name and "195515" not in source.name


def test_reused_oserror_renders_failure_and_source_clock():
    from quick_contract import stage
    from quick_renderer import render
    context = _context()
    context["stages"]["swing"] = stage(
        "swing", "reused", datetime(2026, 9, 10, 16, 55), data_date="2026-09-10",
        source_time="2026-09-10T16:34:51+08:00",
        error={"type": "OSError", "message": "[Errno 22] Invalid argument",
               "traceback_path": None})
    text = render(context)
    assert "⚠️ 本轮获取失败（OSError：[Errno 22] Invalid argument），复用同数据日 16:34 成功结果" in text


def test_reused_without_error_keeps_source_time_note():
    from quick_contract import stage
    from quick_renderer import render
    context = _context()
    context["stages"]["swing"] = stage(
        "swing", "reused", datetime(2026, 9, 10, 16, 55), data_date="2026-09-10",
        source_time="2026-09-10T16:34:51+08:00")
    text = render(context)
    assert "本轮获取失败" not in text
    assert "swing: reused，source=2026-09-10T16:34:51+08:00" in text


def _build_preliminary_delivery(tmp_path, monkeypatch):
    import quick_delivery as delivery
    from quick_contract import sha256_file

    snapshot = tmp_path / "quick-snapshot-20260910-165000.md"
    snapshot.write_text("canonical source", encoding="utf-8")
    context = _context()
    context["generated_at"] = "2026-09-10T16:50:00"
    context["source_snapshot"] = {
        "path": str(snapshot), "sha256": sha256_file(snapshot), "deliverable": False,
    }
    monkeypatch.setattr(delivery, "build_context", lambda *_args, **_kwargs: context)
    *_, manifest_path, manifest = delivery.build_delivery(
        snapshot, output_dir=tmp_path, now=datetime(2026, 9, 10, 16, 50))
    assert manifest["publishable"] is True
    return manifest_path


def test_preliminary_manifest_expires_at_1705(tmp_path, monkeypatch):
    from quick_delivery import verify_delivery

    manifest_path = _build_preliminary_delivery(tmp_path, monkeypatch)
    errors = verify_delivery(manifest_path, now=datetime(2026, 9, 10, 17, 5))
    assert "hook seat temporal invalid" in errors


def test_preliminary_manifest_expires_next_day(tmp_path, monkeypatch):
    from quick_delivery import verify_delivery

    manifest_path = _build_preliminary_delivery(tmp_path, monkeypatch)
    errors = verify_delivery(manifest_path, now=datetime(2026, 9, 11, 10, 0))
    assert "hook seat temporal invalid" in errors


def test_appendix_reader_survives_concurrent_snapshot_deletion(tmp_path, monkeypatch):
    """H21（2026-09-10 审计）：glob→read 之间的并发删除不得炸掉整条 FINAL 链。

    旧实现 `older.read_text()` 的 FileNotFoundError 会冒泡；现改为跳过该候选继续
    找下一份（最后仍按既有语义返回 unverified/failed）。
    """
    import quick_context as qc

    reviews = tmp_path / "output" / "reviews"
    reviews.mkdir(parents=True)
    # 候选①（较新）在 glob 之后被"并发删除"，候选②（较旧）可读 → 应复用②
    older_ok = reviews / "quick-snapshot-20260910-153000-000001.md"
    older_ok.write_text("## 首板题材归类\n\n有效内容\n", encoding="utf-8")
    vanished = reviews / "quick-snapshot-20260910-160000-000002.md"
    vanished.write_text("## 首板题材归类\n\n将被删除\n", encoding="utf-8")

    snapshot = reviews / "quick-snapshot-20260910-164500-000003.md"
    snapshot.write_text("当前快照（无该节）\n", encoding="utf-8")

    real_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self.name == vanished.name:
            raise FileNotFoundError(2, "No such file", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    got = qc._appendix(snapshot, "当前快照（无该节）\n", "首板题材归类", tmp_path,
                       "2026-09-10")
    assert got["status"] == "reused"
    assert "有效内容" in got["text"]
