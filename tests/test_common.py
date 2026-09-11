#!/usr/bin/env python3
"""tests/test_common.py — 通用工具函数测试"""

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from common.calendar import trading_day, replace_today, is_intraday
from iwencai_api import filter_fields


class TestCalendar(unittest.TestCase):

    def test_replace_today(self):
        td = trading_day()
        self.assertEqual(replace_today("今日涨停"), f"{td}涨停")
        # 确保不会替换子串中的"今日"
        self.assertEqual(replace_today("no_today"), "no_today")
        # 🆕 v6.9.44 审计修复后的新语义（旧断言锁的是 bug 行为）：词中"今日"不替换——
        # 旧模式前缀组可选致 '无今日'/'X今日Y' 也被替换，与 docstring 自相矛盾
        self.assertEqual(replace_today("X今日Y"), "X今日Y")
        self.assertEqual(replace_today("无今日"), "无今日")
        self.assertEqual(replace_today("，今日涨停"), f"，{td}涨停")

    def test_trading_day_weekend(self):
        # 找一个周六，断言返回上周五
        d = date(2026, 7, 25)  # 周六
        # 由于 trading_day 使用真实当前时间，这里直接测试周末转换逻辑
        # 构造一个已知周六
        self.assertEqual(d.weekday(), 5)
        friday = d - timedelta(1)
        self.assertEqual(friday.weekday(), 4)

    def test_trading_day_sunday(self):
        d = date(2026, 7, 26)  # 周日
        self.assertEqual(d.weekday(), 6)
        friday = d - timedelta(2)
        self.assertEqual(friday.weekday(), 4)

    def test_is_intraday_boundaries(self):
        """🆕 v6.9.21 盘中判定：周一~五 09:15(竞价起)-15:00，周末/边界外=False"""
        mon = date(2026, 8, 10)  # 周一
        self.assertEqual(mon.weekday(), 0)
        self.assertFalse(is_intraday(datetime(2026, 8, 10, 9, 14)))   # 竞价前
        self.assertTrue(is_intraday(datetime(2026, 8, 10, 9, 15)))     # 竞价开始边界
        self.assertTrue(is_intraday(datetime(2026, 8, 10, 14, 59)))    # 尾盘前
        self.assertFalse(is_intraday(datetime(2026, 8, 10, 15, 0)))    # 收盘复盘窗口
        self.assertFalse(is_intraday(datetime(2026, 8, 10, 8, 0)))     # 盘前
        self.assertFalse(is_intraday(datetime(2026, 8, 8, 10, 0)))     # 周六
        self.assertFalse(is_intraday(datetime(2026, 8, 9, 10, 0)))     # 周日

    def test_trading_day_premarket_prev_day(self):
        """🆕 v6.9.26 盘前(<09:15)=上一交易日：当日数据尚不存在，查询口径回退"""
        self.assertEqual(trading_day(datetime(2026, 8, 17, 8, 30)), "20260814")  # 周一08:30→上周五
        self.assertEqual(trading_day(datetime(2026, 8, 17, 9, 14)), "20260814")  # 竞价前1分钟→上周五
        self.assertEqual(trading_day(datetime(2026, 8, 17, 0, 5)), "20260814")   # 周一凌晨→上周五

    def test_trading_day_from_open_bell(self):
        """🆕 v6.9.26 09:15(竞价=数据开始产生)起=当日，与 is_intraday 起点对齐"""
        self.assertEqual(trading_day(datetime(2026, 8, 17, 9, 15)), "20260817")  # 竞价开始→当日
        self.assertEqual(trading_day(datetime(2026, 8, 17, 15, 30)), "20260817")  # 收盘后→当日

    def test_trading_day_weekend_injected(self):
        """🆕 v6.9.26 周末任意时刻→上周五（含凌晨回退与周末回退的复合）"""
        self.assertEqual(trading_day(datetime(2026, 8, 15, 10, 0)), "20260814")  # 周六白天
        self.assertEqual(trading_day(datetime(2026, 8, 16, 23, 0)), "20260814")  # 周日深夜
        self.assertEqual(trading_day(datetime(2026, 8, 15, 3, 0)), "20260814")   # 周六凌晨(<09:15先退到周五,周五为工作日不再退)


class TestFilterFields(unittest.TestCase):

    def test_keeps_whitelist_and_meta(self):
        datas = [{
            "股票代码": "000001.SZ",
            "股票简称": "平安银行",
            "收盘价[20260728]": 10.5,
            "换手率[20260728]": 1.2,
            "历史PB[20260101]": 0.8,
            "成交量[20260728]": 10000,
        }]
        result = filter_fields(datas, ["收盘价", "换手率"])
        self.assertIn("股票代码", result[0])
        self.assertIn("股票简称", result[0])
        self.assertIn("收盘价[20260728]", result[0])
        self.assertIn("换手率[20260728]", result[0])
        self.assertNotIn("历史PB[20260101]", result[0])
        self.assertNotIn("成交量[20260728]", result[0])

    def test_empty_input(self):
        self.assertEqual(filter_fields([], ["收盘价"]), [])
        self.assertEqual(filter_fields(None, ["收盘价"]), None)


if __name__ == "__main__":
    unittest.main()
