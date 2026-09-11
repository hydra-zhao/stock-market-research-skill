"""example_strategy.py — 示例策略实现（公开演示版）。

⚠️ 免责与边界：
- 本文件是**接口演示**：证明数据管道可以驱动一个满足 interfaces.Protocol
  的策略实现端到端跑通（采集 → 判定 → 渲染 → 交付契约）。
- 全部阈值/权重是**演示值**（SAMPLE_*），与生产参数无关；生产实现私有。
- 解析器只识别本仓库 demo fixtures 生成的快照格式；生产快照的字段远多于此。

接口对齐：quick_context.build_context() 依赖 round1_v2._quick_eval(raw, now)
返回 canonical 字段 dict —— 本模块提供同形状的示例实现，round1_v2 做兼容委托。
"""
from __future__ import annotations

import re
from datetime import datetime, time as dtime

from strategy.interfaces import RegimeVerdict, RiskVerdict, StockScore

# ---- 演示阈值（SAMPLE）——与生产参数无关 ------------------------------
SAMPLE_LIMIT_UP_HOT = 60        # 涨停家数 ≥ 此值视为情绪偏热
SAMPLE_LIMIT_UP_COLD = 20       # 涨停家数 ≤ 此值视为情绪冰点
SAMPLE_BOMB_RATE_WARN = 25.0    # 炸板率 ≥ 此% 视为分歧加大
SAMPLE_MOMENTUM_WEIGHTS = {"ret_5d": 0.4, "vol_ratio": 0.35, "above_ma20": 0.25}

_DIZHI = (
    ("主升", "main_rise"), ("分歧", "divergence"), ("指数", "index"),
    ("犹豫", "hesitation"), ("冰点", "ice"), ("退潮", "retreat"),
    ("恐慌", "panic"), ("混沌", "mixed"),
)


def _section(raw: str, label: str) -> str:
    """提取 `--- [i/n] label [src] desc ---` 段落正文（demo 快照格式）。"""
    pat = re.compile(
        rf"^--- \[\d+/\d+\] {re.escape(label)} \[[^\]]*\][^-]*---\s*$\n(.*?)(?=^--- \[|\Z)",
        re.M | re.S,
    )
    m = pat.search(raw)
    return m.group(1).strip() if m else ""


def _first_number(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except (ValueError, IndexError):
        return None


def _count_table_rows(text: str) -> int | None:
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    rows = [ln for ln in rows if not re.match(r"^\|[\s:\-|]+\|$", ln)]
    return len(rows) if rows else None


def _is_intraday(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return dtime(9, 15) <= now.time() <= dtime(15, 0)


def parse_market_facts(raw: str) -> dict:
    """从 demo 快照文本提取市场事实（缺数据 → None，fail-closed 交给上层）。"""
    facts: dict = {}
    date_m = re.search(r"数据日期[:：]\s*(\d{4}-\d{2}-\d{2})", raw)
    facts["data_date"] = date_m.group(1) if date_m else None
    up = _section(raw, "涨停板")
    facts["limit_up"] = _first_number(up, r"涨停家数\*?\*?[:：]\s*(\d+)") or _count_table_rows(up)
    down = _section(raw, "跌停板")
    facts["limit_down"] = _first_number(down, r"跌停家数\*?\*?[:：]\s*(\d+)") or _count_table_rows(down)
    bomb = _section(raw, "炸板股")
    facts["bomb"] = _first_number(bomb, r"炸板家数\*?\*?[:：]\s*(\d+)") or _count_table_rows(bomb)
    ladder = _section(raw, "连板天梯")
    facts["max_ladder"] = _max_ladder_from_table(ladder)
    idx = _section(raw, "指数行情")
    facts["sh_close"] = _first_number(idx, r"上证指数[^\d]*(\d{3,4}\.\d{2})")
    facts["sh_chg"] = _first_number(idx, r"涨跌幅\[?\d*\]?\*?\*?[:：|]\s*(-?\d+\.\d+)")
    return facts


def _max_ladder_from_table(ladder: str) -> int | None:
    """连板天梯 markdown 表 → 最高连板数（按表头「连板」列索引取值）。"""
    header_idx = None
    best = None
    for line in ladder.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header_idx is None:
            if any("连板" in c for c in cells):
                header_idx = next(i for i, c in enumerate(cells) if "连板" in c)
            continue
        if len(cells) <= header_idx:
            continue
        digits = re.sub(r"\D", "", cells[header_idx])
        if digits.isdigit():
            best = max(best or 0, int(digits))
    return best


def judge_regime(facts: dict, now: datetime | None = None) -> RegimeVerdict:
    """示例生态判定：只做「演示分档」，不做任何真实投资判断。"""
    now = now or datetime.now()
    intraday = _is_intraday(now)
    lu = facts.get("limit_up")
    bomb = facts.get("bomb") or 0
    bomb_rate = round(bomb * 100.0 / (lu + bomb), 1) if (lu is not None and (lu + bomb) > 0) else None

    if lu is None:
        eco, action = "未知（事实缺失，fail-closed）", "观望（事实缺失）"
    elif lu <= SAMPLE_LIMIT_UP_COLD:
        eco, action = "冰点（示例判定）", "防守（示例动作）"
    elif lu >= SAMPLE_LIMIT_UP_HOT and (bomb_rate or 0) < SAMPLE_BOMB_RATE_WARN:
        eco, action = "主升（示例判定）", "可做（示例动作）"
    elif (bomb_rate or 0) >= SAMPLE_BOMB_RATE_WARN:
        eco, action = "分歧（示例判定）", "观望（示例动作）"
    else:
        eco, action = "混沌（示例判定）", "观望（示例动作）"

    return RegimeVerdict(
        data_date=facts.get("data_date") or now.strftime("%Y-%m-%d"),
        eco=eco, intraday=intraday,
        limit_up=lu, limit_down=facts.get("limit_down"),
        bomb=facts.get("bomb"), bomb_rate=bomb_rate,
        max_ladder=facts.get("max_ladder"),
        sh_close=facts.get("sh_close"), sh_chg=facts.get("sh_chg"),
        action=action,
        can_trade_if="示例实现：不输出任何可操作建议" if lu is not None else "事实缺失",
        judges={
            "risk_control": "示例：风控裁决占位（生产实现私有）",
            "quant": "示例：量化裁决占位（生产实现私有）",
            "sentiment": "示例：情绪裁决占位（生产实现私有）",
            "picker": "示例：选股裁决占位（生产实现私有）",
        },
    )


class ExampleScorer:
    """示例个股评分：5日动量 + 量比 + 站上MA20 的等权组合（演示值）。"""

    def score(self, code: str, name: str, facts: dict) -> StockScore:
        total, reasons = 0.0, []
        for key, weight in SAMPLE_MOMENTUM_WEIGHTS.items():
            value = facts.get(key)
            if value is None:
                continue
            norm = max(0.0, min(1.0, value)) if key != "above_ma20" else (1.0 if value else 0.0)
            total += norm * weight
            reasons.append(f"{key}={value}（示例归一 {norm:.2f}×{weight}）")
        tier = "A" if total >= 0.6 else ("B" if total >= 0.3 else "C")
        return StockScore(code=code, name=name, score=round(total, 4), tier=tier, reasons=reasons)


class ExampleRiskGate:
    """示例风险闸：演示 fail-closed 形状（事实缺失 → amber）。"""

    def check(self, code: str, facts: dict) -> RiskVerdict:
        flags = []
        if not facts:
            return RiskVerdict(code=code, level="amber", flags=["示例：无事实可核验"])
        if facts.get("is_st"):
            flags.append("示例：ST 标识")
        if (facts.get("ret_5d") or 0) < -0.15:
            flags.append("示例：近5日深跌")
        level = "red" if "示例：ST 标识" in flags else ("amber" if flags else "green")
        return RiskVerdict(code=code, level=level, flags=flags)


# ---- round1_v2._quick_eval 兼容层 ------------------------------------

def quick_eval_compat(raw: str, now: datetime | None = None) -> dict:
    """对齐生产版 round1_v2._quick_eval 的返回字段（canonical 事实层）。"""
    now = now or datetime.now()
    facts = parse_market_facts(raw)
    verdict = judge_regime(facts, now=now)
    eco_state = "intraday" if verdict.intraday else next(
        (name for token, name in _DIZHI if token in verdict.eco), "unknown")

    def _int0(value):
        """build_context 的 market 层用 int() 承载计数；解析失败按 0 家处理。"""
        return int(value) if value is not None else 0

    return {
        "data_date": verdict.data_date,
        "eco": verdict.eco,
        "eco_state": eco_state,
        "intraday": verdict.intraday,
        "action": verdict.action,
        "can_trade_if": verdict.can_trade_if,
        "limit_up": _int0(verdict.limit_up),
        "limit_down": _int0(verdict.limit_down),
        "bomb": _int0(verdict.bomb),
        "bomb_rate": verdict.bomb_rate,
        "max_ladder": _int0(verdict.max_ladder),
        "sh_close": verdict.sh_close,
        "sh_chg": verdict.sh_chg,
        # schema 契约要求 string；示例实现不判牛熊背景，显式给出"未验证"文案
        "bull_bear": "示例版未验证（生产版由指数均线背景判定）",
        "index_status": "示例版未验证",
        "tui": verdict.judges.get("risk_control"),
        "nie": verdict.judges.get("quant"),
        "yang": verdict.judges.get("sentiment"),
        "jian": verdict.judges.get("picker"),
    }
