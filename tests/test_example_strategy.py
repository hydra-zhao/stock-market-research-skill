# -*- coding: utf-8 -*-
"""示例策略与决策层接口测试（公开版新增）。

锁定三件事：
1. example_strategy 满足 interfaces 的 Protocol 形状；
2. quick_eval_compat 输出与 quick_context.build_context 的字段契约对齐
   （canonical 事实层不缺字段、int 字段不传 None）；
3. demo 快照样例的解析路径端到端可用。
"""
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
for _p in ("data", "data/strategy"):
    if str(_HERE / _p) not in sys.path:
        sys.path.insert(0, str(_HERE / _p))

from strategy import example_strategy as es
from strategy.interfaces import RiskGate, StockScorer


SAMPLE_SNAPSHOT = "\n".join([
    "数据日期: 2026-09-11",
    "--- [1/15] 涨停板 [demo] ---",
    "涨停家数: 86",
    "",
    "| 代码 | 名称 | 涨停原因 |",
    "|---|---|---|",
    "| 300001 | 示例A | 题材X |",
    "--- [2/15] 跌停板 [demo] ---",
    "跌停家数: 3",
    "--- [3/15] 炸板股 [demo] ---",
    "炸板家数: 12",
    "--- [4/15] 连板天梯 [demo] ---",
    "| 代码 | 名称 | 连板 |",
    "|---|---|---|",
    "| 600001 | 示例机械 | 5 |",
    "| 600002 | 示例软件 | 3 |",
    "--- [7/15] 指数行情 [demo] ---",
    "上证指数 3821.44 涨跌幅: 0.82",
])


def test_example_implementations_satisfy_protocols():
    assert isinstance(es.ExampleScorer(), StockScorer)
    assert isinstance(es.ExampleRiskGate(), RiskGate)


def test_parse_market_facts_extracts_all_sections():
    facts = es.parse_market_facts(SAMPLE_SNAPSHOT)
    assert facts["data_date"] == "2026-09-11"
    assert facts["limit_up"] == 86
    assert facts["limit_down"] == 3
    assert facts["bomb"] == 12
    assert facts["max_ladder"] == 5          # 表头列索引解析，不误抓股票代码
    assert facts["sh_close"] == 3821.44
    assert facts["sh_chg"] == 0.82


def test_judge_regime_partitions_and_missing_facts_fail_closed():
    hot = es.judge_regime({"limit_up": 86, "bomb": 12, "data_date": "2026-09-11"},
                          now=datetime(2026, 9, 11, 20, 0))
    cold = es.judge_regime({"limit_up": 10, "bomb": 2, "data_date": "2026-09-11"},
                           now=datetime(2026, 9, 11, 20, 0))
    unknown = es.judge_regime({"limit_up": None}, now=datetime(2026, 9, 11, 20, 0))
    assert "主升" in hot.eco and hot.bomb_rate == 12.2
    assert "冰点" in cold.eco
    assert unknown.eco.startswith("未知")     # 事实缺失 → fail-closed，不硬判
    assert not unknown.intraday


def test_intraday_flag_marks_trading_hours():
    assert es.judge_regime({"limit_up": 60}, now=datetime(2026, 9, 11, 10, 30)).intraday
    assert not es.judge_regime({"limit_up": 60}, now=datetime(2026, 9, 11, 20, 0)).intraday


def test_quick_eval_compat_field_contract():
    compat = es.quick_eval_compat(SAMPLE_SNAPSHOT, now=datetime(2026, 9, 11, 20, 0))
    for key in ("data_date", "eco", "intraday", "action", "limit_up", "limit_down",
                "bomb", "bomb_rate", "max_ladder", "sh_close", "sh_chg",
                "bull_bear", "index_status", "tui", "nie", "yang", "jian"):
        assert key in compat, f"canonical 字段缺失: {key}"
    for key in ("limit_up", "limit_down", "bomb", "max_ladder"):
        assert isinstance(compat[key], int), f"{key} 必须为 int（build_context 直接 int()）"
    for key in ("bull_bear", "index_status", "tui", "nie", "yang", "jian"):
        assert isinstance(compat[key], str), f"{key} 必须为 string（schema 契约）"


def test_scorer_and_risk_gate_shapes():
    score = es.ExampleScorer().score("000001", "示例一",
                                     {"ret_5d": 0.08, "vol_ratio": 1.1, "above_ma20": 1})
    assert score.tier in {"A", "B", "C"} and 0.0 <= score.score <= 1.0
    missing = es.ExampleRiskGate().check("000001", {})
    assert missing.level == "amber"          # 事实缺失 → 不放行也不冤枉（fail-closed 语义）
    assert es.ExampleRiskGate().check("000001", {"is_st": True}).level == "red"
