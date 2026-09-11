#!/usr/bin/env python3
"""tests/test_etf_ak.py — 国家队ETF AKShare 降级路测试

全部用 fake ak 注入，不落网。覆盖：SSE 份额解析（位置列）/日期发现步进/
净申购计算/渲染口径标注/失败路径/深市快照不计 Δ。
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from sources.etf_ak import (find_share_dates, compute_rows, fetch_and_render,
                            _sse_shares, SSE_CODES)

# 监测清单前两只即可代表沪市，测试里给全部 8 只造数据
SHARES_PREV = {c: 100e8 for c in SSE_CODES}
SHARES_LATEST = {c: 100e8 for c in SSE_CODES}
SHARES_LATEST["510300"] = 103.5e8   # +3.5亿份
SHARES_LATEST["510500"] = 98.07e8   # -1.93亿份


class FakeAk:
    """仿 akshare 四接口：scale_sse(date)/scale_szse()/hist_em/spot_em"""
    def __init__(self, dates=None, szse=True, price=4.787, spot_date="20260819", spot_ok=True):
        # dates: {YYYYMMDD: {code: shares}}，不在表内的日期返回空（模拟非交易日/未披露）
        # spot_date: spot 快照的数据日期；spot_ok=False 时 spot 抛异常（测 hist 兜底）
        self.dates = dates or {}
        self.szse = szse
        self.price = price
        self.spot_date = spot_date
        self.spot_ok = spot_ok
        self.hist_calls = 0

    def fund_etf_scale_sse(self, date=None):
        shares = self.dates.get(date)
        if not shares:
            return pd.DataFrame()
        rows = [[i, c, "X", "ETF", date, s] for i, (c, s) in enumerate(shares.items())]
        return pd.DataFrame(rows, columns=["序号", "基金代码", "基金简称", "ETF类型", "统计日期", "基金份额"])

    def fund_etf_scale_szse(self):
        if not self.szse:
            raise RuntimeError("szse down")
        return pd.DataFrame(
            [["159915", "创业板ETF", 171.9e8, 3.7255], ["159919", "沪深300ETF嘉实", 61.3e8, 4.9993],
             ["159999", "无关ETF", 1e8, 1.0]],
            columns=["基金代码", "基金简称", "基金份额", "净值"])

    def fund_etf_hist_em(self, symbol=None, period=None, start_date=None, end_date=None, adjust=None):
        self.hist_calls += 1
        if self.price is None:
            return pd.DataFrame()
        return pd.DataFrame([{"日期": end_date, "收盘": self.price + 100}])  # 与 spot 价区分

    def fund_etf_spot_em(self):
        if not self.spot_ok:
            raise RuntimeError("spot down")
        rows = [{"代码": c, "数据日期": self.spot_date, "最新价": self.price, "昨收": self.price}
                for c in SSE_CODES]
        return pd.DataFrame(rows)


def _ak_two_days():
    return FakeAk(dates={"20260817": SHARES_PREV, "20260818": SHARES_LATEST})


class TestSseShares(unittest.TestCase):
    def test_parse_positional_cols(self):
        out = _sse_shares("20260818", _ak_two_days())
        self.assertEqual(out["510300"], 103.5e8)
        self.assertEqual(len(out), len(SSE_CODES))

    def test_empty_on_unknown_date(self):
        self.assertEqual(_sse_shares("20260816", _ak_two_days()), {})

    def test_exception_returns_empty(self):
        class Boom:
            def fund_etf_scale_sse(self, date=None):
                raise RuntimeError("net err")
        self.assertEqual(_sse_shares("20260818", Boom()), {})


class TestFindDates(unittest.TestCase):
    def test_steps_back_over_weekend(self):
        # today=周三 8/19 → 先试 8/18 命中 latest，8/17 命中 prev
        latest, prev = find_share_dates(_ak_two_days(), today="20260819")
        self.assertEqual((latest, prev), ("20260818", "20260817"))

    def test_skips_unpublished_t1(self):
        # 早8:00前 T-1 未披露（8/18 无数据）→ 自动落到 8/17 / 8/14
        ak = FakeAk(dates={"20260817": SHARES_LATEST, "20260814": SHARES_PREV})
        latest, prev = find_share_dates(ak, today="20260819")
        self.assertEqual((latest, prev), ("20260817", "20260814"))

    def test_no_data_returns_none(self):
        latest, prev = find_share_dates(FakeAk(), today="20260819")
        self.assertIsNone(latest)
        self.assertIsNone(prev)


class TestComputeRows(unittest.TestCase):
    def test_delta_and_amount(self):
        prices = {c: 4.787 for c in SSE_CODES}
        rows, total = compute_rows(SHARES_LATEST, SHARES_PREV, prices)
        self.assertEqual(len(rows), len(SSE_CODES))
        r300 = next(r for r in rows if r[0] == "510300")
        self.assertAlmostEqual(r300[4], 3.5, places=6)          # Δ +3.5亿份
        self.assertAlmostEqual(r300[6], 3.5 * 4.787, places=6)  # 净申购估算
        self.assertAlmostEqual(total, (3.5 - 1.93) * 4.787, places=6)

    def test_missing_price_amt_none_and_excluded_from_total(self):
        prices = {c: 4.787 for c in SSE_CODES}
        del prices["510300"]
        rows, total = compute_rows(SHARES_LATEST, SHARES_PREV, prices)
        r300 = next(r for r in rows if r[0] == "510300")
        self.assertIsNone(r300[6])
        self.assertAlmostEqual(total, -1.93 * 4.787, places=6)  # 只剩 510500 的 Δ

    def test_missing_code_skipped(self):
        prev = dict(SHARES_PREV)
        del prev["510300"]
        rows, _ = compute_rows(SHARES_LATEST, prev, {c: 1.0 for c in SSE_CODES})
        self.assertNotIn("510300", [r[0] for r in rows])


class TestRenderAndFlow(unittest.TestCase):
    def test_render_marks_szse_not_counted(self):
        ok, body = fetch_and_render(ak=_ak_two_days(), sleep_fn=lambda s: None, today="20260819")
        self.assertTrue(ok)
        self.assertIn("20260818", body)
        self.assertIn("未计入", body)
        self.assertIn("沪市合计", body)
        self.assertIn("收盘价代理净值", body)

    def test_spot_primary_no_hist_calls(self):
        ak = _ak_two_days()
        ok, _ = fetch_and_render(ak=ak, sleep_fn=lambda s: None, today="20260819")
        self.assertTrue(ok)
        self.assertEqual(ak.hist_calls, 0)  # spot 单次调用覆盖全部价格，不逐只 hist

    def test_spot_date_same_day_uses_latest_price(self):
        # spot 数据日期==份额数据日（盘前场景）→ 用最新价而非昨收
        ak = FakeAk(dates={"20260817": SHARES_PREV, "20260818": SHARES_LATEST},
                    spot_date="20260818")
        ok, body = fetch_and_render(ak=ak, sleep_fn=lambda s: None, today="20260819")
        self.assertTrue(ok)
        self.assertEqual(ak.hist_calls, 0)

    def test_spot_stale_falls_back_hist(self):
        # spot 数据日期<份额数据日（异常陈旧）→ resolve 返回 None → hist 兜底
        ak = FakeAk(dates={"20260817": SHARES_PREV, "20260818": SHARES_LATEST},
                    spot_date="20260817")
        ok, body = fetch_and_render(ak=ak, sleep_fn=lambda s: None, today="20260819")
        self.assertTrue(ok)
        self.assertGreater(ak.hist_calls, 0)
        self.assertIn(f"{4.787 + 100:.3f}", body)  # hist 兜底价流入表格

    def test_szse_snapshot_failure_still_ok(self):
        ok, body = fetch_and_render(ak=FakeAk(dates={"20260817": SHARES_PREV,
                                                     "20260818": SHARES_LATEST}, szse=False),
                                    sleep_fn=lambda s: None, today="20260819")
        self.assertTrue(ok)
        self.assertIn("未计入", body)

    def test_no_dates_fails(self):
        ok, body = fetch_and_render(ak=FakeAk(), sleep_fn=lambda s: None, today="20260819")
        self.assertFalse(ok)
        self.assertIn("无数据", body)

    def test_single_day_fails(self):
        ok, body = fetch_and_render(ak=FakeAk(dates={"20260818": SHARES_LATEST}),
                                    sleep_fn=lambda s: None, today="20260819")
        self.assertFalse(ok)
        self.assertIn("无对照日", body)

    def test_price_all_missing_still_renders_delta(self):
        ok, body = fetch_and_render(ak=FakeAk(dates={"20260817": SHARES_PREV,
                                                     "20260818": SHARES_LATEST},
                                              price=None, spot_ok=False),
                                    sleep_fn=lambda s: None, today="20260819")
        self.assertTrue(ok)
        self.assertIn("+3.50", body)   # Δ份额照常展示


if __name__ == "__main__":
    unittest.main()
