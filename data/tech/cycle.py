#!/usr/bin/env python3
"""tech/cycle.py — 周期定位规则引擎（公开演示版）。

生产版：十大强周期行业的参数化引擎 —— 每个行业配置领先/同步指标查询
+ 数值阈值规则（底部/顶部特征），从原始查询输出中自动提取指标值、
命中规则出信号（约 570 行，行业判据来自私有知识库 industry-cycles.md，
不在公开版提供）。

公开版保留**引擎概念**的最小可运行示例：
配置驱动的阈值规则匹配器 + 一个虚构示例行业，演示
「行业配置 → 指标事实 → 规则命中 → 信号清单」的管线形状。

⚠️ 示例行业 "demo_steel" 的指标名与阈值均为虚构演示值。
"""

# ── 行业配置结构（示例） ─────────────────────────────────
# queries: (label, source, query, limit) —— 生产版由 builders 按此生成采集任务
# rules  : metric 关键词定位指标值，op/th 做阈值比较，side 标注底部/顶部特征
CYCLES = {
    "demo_steel": {
        "name": "示例行业（虚构，仅演示引擎形状）",
        "aliases": {"demo", "示例行业"},
        "queries": [
            ("示例库存指标", "iw:hithink-macro-query", "<生产版由 builders 生成>", 6),
            ("示例价格指标", "iw:hithink-futures-query", "<生产版由 builders 生成>", 3),
        ],
        "rules": [
            {"section": "示例库存指标", "metric": ("库存",), "op": "<", "th": 100.0,
             "side": "bottom", "desc": "示例：库存低于阈值=去化到位（底部特征）"},
            {"section": "示例价格指标", "metric": ("价格", "最新价"), "op": ">", "th": 5000.0,
             "side": "top", "desc": "示例：价格高于阈值=盈利过热（顶部特征）"},
        ],
        "note": "示例行业：只演示配置结构，不代表任何真实行业判据",
    },
}

# 生产版：部分行业不走本框架（知识库附录说明）
NON_CYCLE_HINT = {
    "半导体": "<生产版：库存/CAPEX 双框架，见知识库附录>",
}


def resolve_industry(arg: str):
    """别名 → 行业配置（未命中返回 None）。"""
    key = (arg or "").strip().lower()
    for cycle_key, cfg in CYCLES.items():
        if key == cycle_key or key in cfg.get("aliases", set()):
            return cycle_key, cfg
    return None


def evaluate_rules(values: dict, rules: list) -> list:
    """规则引擎核心（纯函数，零网络）。

    values: {section: {metric关键词: 数值}} —— 由生产版的指标提取层
            （extract_metric/extract_series）从查询输出中产出；
            公开版直接接受已归一化的数值。
    返回命中信号清单；比较符仅支持 < > <= >=（与生产版一致的最小子集）。
    """
    hits = []
    for rule in rules or []:
        section_vals = values.get(rule["section"], {}) or {}
        for metric_key, value in section_vals.items():
            if not any(k in metric_key for k in rule["metric"]):
                continue
            if value is None:
                continue  # 伪值/缺失护栏：不硬判（与生产版 fail-closed 同语义）
            th, op = rule["th"], rule["op"]
            matched = (
                (op == "<" and value < th) or (op == ">" and value > th)
                or (op == "<=" and value <= th) or (op == ">=" and value >= th)
            )
            if matched:
                hits.append({**rule, "value": value})
                break
    return hits


def evaluate_cycle(key: str, values: dict) -> dict:
    """行业 → 信号命中清单（生产版从原始查询输出提取指标；公开版入参即数值）。"""
    resolved = resolve_industry(key) or (key, CYCLES.get(key))
    if not resolved or resolved[1] is None:
        return {"industry": key, "hits": [], "note": "未注册行业"}
    _, cfg = resolved
    hits = evaluate_rules(values, cfg.get("rules"))
    return {
        "industry": key, "name": cfg.get("name", key),
        "hits": hits, "note": cfg.get("note", ""),
    }
