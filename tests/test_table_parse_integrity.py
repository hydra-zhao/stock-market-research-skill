# -*- coding: utf-8 -*-
"""审计收口（D）N2b：表格解析不得静默丢行。

旧实现 `if len(values) == len(header)` 把列数不匹配的整行丢掉——没有旁路、
没有计数、调用方无从知晓；`_parse_holdings` 还有第二处 `len(code)!=6 or not
name → continue`。后果不是"少一行显示"，而是按调用点改变产出语义：
- 持仓段丢一行 → `actions.existing_longterm.allowed = bool(holdings)` 可能由
  True 翻 False（交易权限）；若唯一一行解析失败，等于台账"被清空"。
- 昨日连板表现丢一行 → 该股**既不在断板名单也不在未验证名单**，凭空从统计消失。
- 涨停板丢一行 → 龙头晋级判定漏判。

本组锁定：原始行原样进 malformed 通道、权威字段不受污染、账目自洽、正文可见。
夹具按 round1_v2 真实段落语法（`--- [N/M] 段名 [源] OK (0.0s) ---`）构造，
保证走的是生产同一条抽取路径，而不是为测试特供的旁路格式。
"""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE / "data"))

import quick_context as qc

NOW = datetime.fromisoformat("2026-09-10T17:05:00+08:00")

LADDER_CLEAN = ("| 股票代码 | 股票简称 | 连续涨停天数 |\n"
                "|---|---|---|\n"
                "| 600000.SH | 甲 | 3 |")
LADDER_DIRTY = LADDER_CLEAN + "\n| 600001.SZ | 乙 | 2 | 多出来一列 |"

PREVIOUS = ("| 股票代码 | 股票简称 | 连续涨停天数[20260909] | 涨跌幅[20260910] |\n"
            "|---|---|---|---|\n"
            "| 600002.SZ | 丙 | 2.0 | -3.20 |")

UP_BOARD = "| 股票代码 | 股票简称 |\n|---|---|\n| 600003.SH | 丁 |"

FUTURES = ("| 品种 | 多头持仓 | 空头持仓 | 净持仓 |\n"
           "|---|---|---|---|\n| 合计 | 1 | 2 | -1 |")


def _snapshot(ladder: str) -> str:
    blocks = [("涨停板", "fuyao", UP_BOARD), ("连板天梯", "fuyao", ladder),
              ("昨日连板表现", "iw", PREVIOUS), ("期指持仓", "ak", FUTURES),
              ("国家队ETF", "ak", "数据日期：20260909")]
    body = "".join(f"--- [{i}/{len(blocks)}] {name} [{src}] OK (0.0s) ---\n\n{text}\n\n"
                   for i, (name, src, text) in enumerate(blocks, 1))
    return ("# quick 原始输出（测试夹具）2026-09-10\n\n" + body
            + "--- [local] 首板题材归类 v7.0.13 [OK] ---\n无确认主线\n\n"
            + "## 📈 趋势波段候选（3-20交易日）\n\n无合格标的\n\n"
            + "## 🇺🇸 美股指数ETF估值/位置观察（仅 QQQ、SPY）\n\nQQQ/SPY 未触发观察阈值\n")


POSITIONS = """# 持仓台账（测试夹具）
## 持仓明细
| 代码 | 名称 | 轨道 | 成本 |
|---|---|---|---|
| 600004 | 戊 | 长线底仓 | 10.00 |
| 60000 | 己 | 长线底仓 | 11.00 |
| 600005 | 庚 | 长线底仓 |
"""

POSITIONS_CLEAN = """# 持仓台账（测试夹具）
## 持仓明细
| 代码 | 名称 | 轨道 | 成本 |
|---|---|---|---|
| 600004 | 戊 | 长线底仓 | 10.00 |
"""

POSITIONS_ALL_BAD = """# 持仓台账（测试夹具）
## 持仓明细
| 代码 | 名称 | 轨道 | 成本 |
|---|---|---|---|
| 60000 | 己 | 长线底仓 | 11.00 |
"""


class TableCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.snapshot = self.root / "quick-snapshot-20260910-170500.md"

    def _context(self, ladder=LADDER_DIRTY, positions=POSITIONS):
        self.snapshot.write_text(_snapshot(ladder), encoding="utf-8")
        pos = self.root / "positions.md"
        pos.write_text(positions, encoding="utf-8")
        return qc.build_context(self.snapshot, now=NOW, positions_path=pos, root=self.root)


class TestTableExUnit(unittest.TestCase):
    def test_mismatched_rows_are_preserved_not_dropped(self):
        block = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 | 5 |\n"
        rows, malformed = qc._table_ex(block)
        self.assertEqual(rows, [{"A": "1", "B": "2"}])
        self.assertEqual(len(malformed), 1, "列数不匹配的行必须进 malformed")
        self.assertEqual(malformed[0]["reason"], "column_count_mismatch")
        self.assertEqual(malformed[0]["raw"], "| 3 | 4 | 5 |", "原始行必须原样保留")
        self.assertEqual((malformed[0]["cells"], malformed[0]["header_cells"]), (3, 2))

    def test_clean_table_has_no_malformed(self):
        rows, malformed = qc._table_ex("| A | B |\n|---|---|\n| 1 | 2 |\n")
        self.assertEqual(rows, [{"A": "1", "B": "2"}])
        self.assertEqual(malformed, [])

    def test_short_block_is_empty_not_malformed(self):
        self.assertEqual(qc._table_ex("| A | B |"), ([], []))

    def test_table_wrapper_keeps_legacy_contract(self):
        block = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 | 5 |\n"
        self.assertEqual(qc._table(block), qc._table_ex(block)[0])


class TestHoldingsExUnit(TableCase):
    def test_unparsable_code_is_malformed_not_dropped(self):
        path = self.root / "p.md"
        path.write_text(POSITIONS, encoding="utf-8")
        holdings, malformed = qc._parse_holdings_ex(path)
        self.assertEqual([h["code"] for h in holdings], ["600004"])
        reasons = sorted(x["reason"] for x in malformed)
        self.assertEqual(reasons, ["code_or_name_unparsable", "column_count_mismatch"])

    def test_malformed_raw_is_the_original_row(self):
        """取值不可解析时，raw 必须是**原始行**（按表头顺序还原），不是摘要。"""
        path = self.root / "p.md"
        path.write_text(POSITIONS, encoding="utf-8")
        _holdings, malformed = qc._parse_holdings_ex(path)
        bad = next(x for x in malformed if x["reason"] == "code_or_name_unparsable")
        self.assertEqual(bad["raw"], "| 60000 | 己 | 长线底仓 | 11.00 |")

    def test_legacy_wrapper_returns_rows_only(self):
        path = self.root / "p.md"
        path.write_text(POSITIONS, encoding="utf-8")
        self.assertEqual(qc._parse_holdings(path), qc._parse_holdings_ex(path)[0])

    def test_missing_file_is_empty(self):
        self.assertEqual(qc._parse_holdings_ex(self.root / "nope.md"), ([], []))


class TestBuildContextAccounting(TableCase):
    def test_malformed_surfaces_with_counts_and_raw_rows(self):
        tp = self._context()["sections"]["table_parse"]
        self.assertEqual(tp["malformed_counts"],
                         {"ladder": 1, "previous": 0, "current_up": 0, "holdings": 2})
        self.assertEqual(tp["parsed"],
                         {"ladder": 1, "previous": 1, "current_up": 1, "holdings": 1})
        self.assertEqual({x["section"] for x in tp["malformed"]},
                         {"ladder", "holdings"})
        ladder_bad = next(x for x in tp["malformed"] if x["section"] == "ladder")
        self.assertIn("多出来一列", ladder_bad["raw"])

    def test_authoritative_fields_are_not_polluted(self):
        """malformed 行不得混进权威字段——只进账，不进 holdings/梯队/断板。"""
        context = self._context()
        self.assertEqual([h["code"] for h in context["holdings"]], ["600004"])
        self.assertNotIn("己", str(context["holdings"]))
        self.assertEqual(len(context["sections"]["ladder"]), 1)
        self.assertEqual(context["sections"]["ladder"][0]["股票简称"], "甲")

    def test_context_passes_schema_and_semantic_contract(self):
        self.assertEqual(qc.validate_context(self._context()), [])

    def test_clean_parse_is_a_valid_context(self):
        context = self._context(ladder=LADDER_CLEAN, positions=POSITIONS_CLEAN)
        self.assertEqual(qc.validate_context(context), [])
        self.assertEqual(context["sections"]["table_parse"]["malformed"], [])

    def test_counts_must_match_listed_rows(self):
        context = self._context()
        context["sections"]["table_parse"]["malformed_counts"]["ladder"] = 7
        self.assertTrue(any("table_parse ladder count" in e
                            for e in qc.validate_context(context)))

    def test_malformed_row_without_raw_is_rejected(self):
        context = self._context()
        context["sections"]["table_parse"]["malformed"].append(
            {"section": "ladder", "raw": "", "cells": 1, "header_cells": 2,
             "reason": "column_count_mismatch"})
        context["sections"]["table_parse"]["malformed_counts"]["ladder"] = 2
        errors = qc.validate_context(context)
        self.assertTrue(any("raw" in e for e in errors),
                        f"无原始行的 malformed 必须 fail-closed，实得 {errors}")

    def test_legacy_context_without_table_parse_is_rejected(self):
        context = self._context()
        context["sections"].pop("table_parse")
        self.assertTrue(qc.validate_context(context),
                        "缺解析完整性账必须 fail-closed（schema required）")


class TestHoldingsPermissionEdge(TableCase):
    def test_malformed_row_does_not_grant_permission(self):
        """解析失败的行**不得**被当成持仓补回（不能凭空给仓位权限）。"""
        context = self._context(positions=POSITIONS_ALL_BAD)
        self.assertEqual(context["holdings"], [])
        self.assertFalse(context["actions"]["existing_longterm"]["allowed"])
        self.assertEqual(context["sections"]["table_parse"]["malformed_counts"]["holdings"], 1)

    def test_single_valid_row_still_grants_and_bad_rows_are_visible(self):
        context = self._context()
        self.assertTrue(context["actions"]["existing_longterm"]["allowed"])
        self.assertEqual(context["sections"]["table_parse"]["malformed_counts"]["holdings"], 2)


class TestRendererVisibility(TableCase):
    def _render(self, ladder=LADDER_DIRTY, positions=POSITIONS):
        from quick_renderer import render
        return render(self._context(ladder=ladder, positions=positions))

    def test_malformed_rows_are_rendered_in_deliverable(self):
        body = self._render()
        self.assertIn("表格解析：", body)
        self.assertIn("未解析行", body)
        self.assertIn("column_count_mismatch", body)
        self.assertIn("多出来一列", body, "原始行必须出现在交付正文里")
        self.assertIn("code_or_name_unparsable", body)
        self.assertIn("| 60000 | 己 | 长线底仓 | 11.00 |", body)

    def test_column_counts_only_shown_for_mismatch(self):
        body = self._render()
        self.assertIn("列数 4≠3 ", body)
        self.assertNotIn("列数 4≠4 ", body, "取值不可解析时列数相等，写出来是噪音")

    def test_clean_parse_renders_counts_without_warning(self):
        body = self._render(ladder=LADDER_CLEAN, positions=POSITIONS_CLEAN)
        self.assertIn("表格解析：", body)
        self.assertNotIn("未解析行", body)


if __name__ == "__main__":
    unittest.main()
