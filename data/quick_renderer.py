"""Deterministic FINAL-001 renderer. Accepts canonical context only."""
from __future__ import annotations

import re
from pathlib import Path

from quick_contract import seat_label


def _f2(value, signed: bool = False) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "未验证"
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def _f1(value, signed: bool = False) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "未验证"
    return f"{value:+.1f}" if signed else f"{value:.1f}"


def _p2(value, signed: bool = False) -> str:
    """百分数（2dp）：缺失输出"未验证"，不带 %尾巴。"""
    text = _f2(value, signed=signed)
    return text + "%" if text != "未验证" else text


def _p1(value, signed: bool = False) -> str:
    text = _f1(value, signed=signed)
    return text + "%" if text != "未验证" else text


def _fi(value) -> str:
    return f"{value:,.0f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "未验证"


def _change_bits(facts: dict) -> list[str]:
    bits = []
    for name, key in (("净多chg", "citic_net_change"), ("多chg", "citic_long_change"),
                      ("空chg", "citic_short_change")):
        value = facts.get(key)
        if value is not None:
            bits.append(f"{name} {value:+,}")
    return bits


def _compact_futures(facts: dict | None) -> str:
    """期指一句话：只消费 canonical facts，不再从原始文本猜数字。"""
    facts = facts or {}
    label = facts.get("label")
    if not label:
        return "期指数据未采集或无法解析（未验证，不产生方向结论）"
    result = label
    net_short = facts.get("citic_net_short")
    if net_short is not None:
        result += f"；中信净空 {net_short:,} 手"
    changes = _change_bits(facts)
    if changes:
        result += "（" + "｜".join(changes) + "）"
    top15 = facts.get("top15_net_change")
    if top15 is not None:
        result += f"；Top15 净多chg {top15:+,}"
    missing = list(facts.get("unverified_fields") or [])
    if missing:
        result += "；⚠️ 未验证字段：" + "/".join(missing)
    return result


def _compact_etf(text: str) -> str:
    date = re.search(r"数据日期[：:]\s*(\d{8})", text)
    total = re.search(r"\*\*沪市合计\*\*[^\n]*\*\*([+-]?[\d.]+)\*\*", text)
    return f"国家队ETF数据日 {date.group(1) if date else '未验证'}；沪市合计 {total.group(1) + '亿' if total else '未验证'}"


def _reused_note(item: dict) -> str:
    """N8：复用必须写明"本轮失败 + 复用自哪一刻的成功结果 + 简短错误"。"""
    source = str(item.get("source_time") or "")
    clock = f"{source[11:16]}" if len(source) >= 16 and source[10] == "T" else (source or "时间未验证")
    error = item.get("error") or {}
    detail = "：".join(x for x in (error.get("type"), error.get("message")) if x) or "原因未记录"
    return f"⚠️ 本轮获取失败（{detail}），复用同数据日 {clock} 成功结果"


def _stage_note(item: dict) -> str:
    bits = [str(item["status"])]
    if item.get("status") == "reused" and item.get("error"):
        bits.append(_reused_note(item))
    elif item.get("source_time"):
        bits.append(f"source={item['source_time']}")
    if not item.get("temporal_valid", False):
        bits.append("temporal_valid=false")
    if item.get("stage_id") == "seat":
        # N4：忠实显示 seat_profile 的原始状态 + 交付策略含义，不折叠、不美化。
        bits.append(seat_label(str(item["status"])))
    return "，".join(bits)


def _without_outer_h2(text: str) -> str:
    return re.sub(r"^##[^\n]*\n+", "", text.strip(), count=1)


def _swing_summary_lines(context: dict) -> list[str]:
    """swing 附录摘要化：分层结论 + 逐票风险层 + 可深查清单 + 对象说明。

    🆕 v7.3.5：全文（TopN 前复权校准、板块资金大表、逐票风险扫描明细）不进
    交付正文——大表对读者是噪声，事实仍完整保留在落盘快照与 canonical
    context 里。摘要三态：结构化摘要 / 格式未识别（显式未验证）/ 候选未验证。
    """
    summary = context["sections"].get("swing_summary")
    source = context["stages"]["swing"].get("source_path")
    source_name = Path(source).name if source else "落盘快照"
    if summary:
        eligible = [c for c in summary["candidates"] if c["eligible"]]
        lines = ["", summary["stratification_line"], "",
                 "| 代码 | 名称 | 风险层 | 六要素深查 |", "|---|---|---|---|"]
        for c in summary["candidates"]:
            tier_label = c.get("tier_label") or c["tier"]
            lines.append(f"| {c['code']} | {c['name']} | {tier_label} | "
                         f"{'✔ 可深查' if c['eligible'] else '✘ 出局'} |")
        if eligible:
            names = "、".join(f"{c['name']}（{c['code']}）" for c in eligible)
            lines += ["", f"可进六要素深查清单：{names}；未完成深查前不视为合适标的。"]
        else:
            lines += ["", "本轮无清洁/标注级候选，保持空池。"]
        lines += ["",
                  f"- 说明：对象=趋势波段初筛 TopN 候选（非持仓/自选）；🟠/🔴 自动出局不得深查；"
                  f"TopN 前复权精度校准、板块资金与逐票风险扫描明细不进交付正文，"
                  f"全文见落盘快照 `{source_name}`。", ""]
        return lines
    if context["sections"].get("swing"):
        return ["", f"初筛明细未解析为结构化摘要（附录格式未识别，候选明细未验证）；"
                    f"全文见落盘快照 `{source_name}`。", ""]
    return ["", "候选未验证。", ""]


def _holding_quote_cell(holding: dict) -> str:
    """持仓今日收盘单元格：verified 才出数字，否则未验证（fail-closed）。"""
    quote = holding.get("quote") or {}
    if quote.get("status") != "verified":
        return "未验证"
    cell = f"{quote['close']:.2f}（{quote['change_pct']:+.2f}%"
    if quote.get("turnover") is not None:
        cell += f"，额 {quote['turnover']:.2f}亿"
    return cell + "）"


def _tri(value) -> str:
    return "✓" if value is True else "✗" if value is False else "未验证"


def _plan_lines(title: str, items: list[str]) -> list[str]:
    return [f"**{title}**"] + ([f"- {item}" for item in items] if items else ["- 未生成：相关事实未验证。"]) + [""]


def render(context: dict) -> str:
    if context.get("artifact_type") != "quick_context":
        raise ValueError("quick_renderer only accepts canonical quick_context")
    m, eco, actions = context["market"], context["eco"], context["actions"]
    verdicts = eco["verdicts"]
    holdings = context["holdings"]
    leaders = context["leaders"]
    ladder_rows = context["sections"]["ladder"]
    broken = context["sections"]["broken_boards"]
    unverified = context["sections"].get("broken_boards_unverified") or []
    relay = context["relay_analysis"]
    mainline = context["mainline_analysis"]
    plan = context["tomorrow_plan"]

    lines = [
        f"# 快速复盘 · {context['data_date']}", "",
        "> FINAL-001：正文由 canonical context 确定性生成；原始 snapshot 不可交付。", "",
        "## ⚡ 快速复盘 TL;DR", "",
        f"**一句话结论**：{eco['label']}"
        + (f"；{m['bull_bear']}" if m.get("bull_bear") else "")
        + (f"；超短接力新开仓上限 {actions['ultra_relay']['max_new_position_pct']}%"
           if actions['ultra_relay']['max_new_position_pct'] is not None
           else "；超短接力新开仓上限按既有规则"), "",
        "## 关键信号（四人裁决）", "",
        "| 裁决人 | 信号 |", "|---|---|",
        f"| 退神 | {verdicts['tuishen']} |", f"| 涅槃 | {verdicts['niepan']} |",
        f"| 养家 | {verdicts['yangjia']} |", f"| 见股起意 | {verdicts['jianguqiyi']} |", "",
        "## 核心数据", "",
        f"- 涨停 {m['limit_up']} 家（比 {_f2(m.get('zt_ratio'))}，30日均 {_fi(m.get('zt_mean'))} 家）"
        f" / 跌停 {m['limit_down']} 家（比 {_f2(m.get('dt_ratio'))}，30日均 {_fi(m.get('dt_mean'))} 家）"
        f" / 炸板 {m['bomb']} 家（炸板率 {_p1(m.get('bomb_rate'))}，封板率 {_p1(m.get('seal_rate'))}）。",
        f"- 量能比 {_f2(m.get('vol_ratio'))}（今日÷30日均成交 {_fi(m.get('amt_mean'))} 亿），"
        f"环比 {_p1(m.get('dod_pct'), signed=True)}{m.get('vol_price') or ''}；"
        f"最高 {m['max_ladder']} 板。",
        f"- 接力情绪：昨日涨停今日溢价 {_p2(m.get('premium_avg'), signed=True)}"
        f"｜晋级率 {_p1(m.get('promo_rate'))}"
        + (f"｜封板率分层 10cm {_p1(m.get('seal10'))} / 20cm {_p1(m.get('seal20'))}"
           if m.get("seal10") is not None or m.get("seal20") is not None else "｜封板率分层未验证") + "。",
        f"- 指数底色：上证 {_f2(m['index_close']) if m['index_close'] is not None else '未验证'}"
        f"（{_p2(m['index_change_pct'], signed=True) if m['index_change_pct'] is not None else '未验证'}）"
        f" vs MA360 {_f2(m.get('ma360'))} vs MA250 {_f2(m.get('ma250'))}"
        + (f"（{m['index_status']}）" if m.get("index_status") else "") + "。",
        f"- 市场广度：上涨 {m['breadth_up'] if m['breadth_up'] is not None else '未验证'} / 下跌 {m['breadth_down'] if m['breadth_down'] is not None else '未验证'}；"
        f"成交额 {m['turnover'] if m['turnover'] is not None else '未验证'} 亿。",
        "",
        "## 聪明资金一句话（期指 + ETF 各一句）", "",
        f"- 期指：{_compact_futures(context['sections'].get('futures_facts'))}。",
        f"- ETF：{_compact_etf(context['sections']['national_etf'])}。", "",
        "## 连板梯队表 + 断板名单 + 解读", "",
        "| 代码 | 名称 | 连板 |", "|---|---|---|",
    ]
    if ladder_rows:
        for row in ladder_rows:
            code = next((v for k, v in row.items() if "代码" in k), "")
            name = next((v for k, v in row.items() if "简称" in k), "")
            boards = next((v for k, v in row.items() if "连续涨停" in k), "")
            lines.append(f"| {code} | {name} | {boards} |")
    else:
        lines.append("| — | 无已验证梯队 | — |")
    broken_text = "；".join(f"{x['name']}（昨{x['previous_boards']}板，今{x['change_pct']:+.2f}%）" for x in broken[:12]) or "无已验证断板样本"
    unverified_text = "；".join(
        f"{x['name']}（昨{x['previous_boards']}板，涨跌幅未验证）" for x in unverified[:12])
    lines += ["", f"**断板名单**：{broken_text}。", "", "**一句话解读**：梯队与断板均直接来自 canonical context，不由 Agent 二次选择口径。", ""]
    if unverified_text:
        lines += [f"**未验证（不判断板）**：{unverified_text}；缺涨跌幅即不判定，未验证 ≠ 断板。", ""]
    lines += ["## 接力与亏钱效应", "",
              f"- 高度：{relay['max_ladder'] if relay['max_ladder'] is not None else '未验证'} 板；"
              f"晋级率 {_p1(relay.get('advancement_rate'))}；昨日涨停溢价 {_p2(relay.get('prior_limit_premium'), signed=True)}。",
              f"- 断板 {relay['broken_count'] if relay['broken_count'] is not None else '未验证'} 家；"
              f"大面 {relay['big_loss_count'] if relay['big_loss_count'] is not None else '未验证'} 家"
              f"（解释口径：断板后跌幅≤{relay['big_loss_threshold_pct']:.0f}%，非交易阈值）。",
              f"- 状态：`{relay['state']}`。{relay['interpretation']}", ""]
    lines += [
              "## 首板题材归类", "", context["sections"]["first_board"] or "未验证。", "",
              "## 主线确认", "",
              "| 题材 | 涨停家数 | ≥2板高度 | 资金TOP10 | 主线确认 | 状态 |",
              "|---|---:|---|---|---|---|",
              ]
    if mainline["themes"]:
        for item in mainline["themes"]:
            total = item["total_limit_count"] if item["total_limit_count"] is not None else "未验证"
            lines.append(f"| {item['theme']} | {total} | {_tri(item['has_2plus_board'])} | "
                         f"{_tri(item['fund_top10'])} | {item['pass_count']}/{item['required']} | {item['status']} |")
    else:
        lines.append("| — | 未验证 | 未验证 | 未验证 | 0/2 | unverified |")
    lines += ["", mainline["summary"], "",
              "## 持仓对照", ""]
    if holdings:
        lines += ["| 代码 | 名称 | 轨道 | 成本 | 今日收盘 | 状态 |", "|---|---|---|---|---|---|"]
        for h in holdings:
            lines.append(f"| {h['code']} | {h['name']} | {h['track']} | {h['cost']} | "
                         f"{_holding_quote_cell(h)} | {h['status']}；按原轨道管理 |")
        lines += ["", "今日收盘列=本地完成日K叠加（market_dump，零配额）；未验证=本地底座"
                  "无当日 bar（不代表停牌）。台账为持仓唯一事实源；订单/卖单成交状态"
                  "不在本层，须另行核验。"]
    else:
        lines.append("当前台账无持仓。")
    if leaders:
        lines += ["", "明日龙头观察：" + "；".join(
            f"{x['theme']}·{x['name']}（{x['code']}，{x['boards_as_of'] or '来源日未验证'} {x['boards']}板，{x['current_status']}"
            f"{(' ' + format(x['current_change_pct'], '+.2f') + '%') if x['current_change_pct'] is not None else ''}，仅观察）"
            for x in leaders) + "。"]
    lines += ["", "## 明日计划", ""]
    lines += _plan_lines("可做条件", plan["can_trade_if"])
    lines += _plan_lines("继续空仓条件", plan["stay_out_if"])
    lines += _plan_lines("重点观察", plan["watch_focus"])
    lines += _plan_lines("持仓关注", plan["holding_focus"])
    lines += ["", "## 📈 趋势波段候选", "", f"状态：{_stage_note(context['stages']['swing'])}。"]
    lines += _swing_summary_lines(context)
    lines += ["## 美股指数 ETF 观察", "", f"状态：{_stage_note(context['stages']['us_etf'])}。",
              _without_outer_h2(context["sections"]["us_etf"]) if context["sections"]["us_etf"] else "QQQ/SPY 未验证。", "",
              "## 数据采集自检", ""]
    for name, item in context["stages"].items():
        lines.append(f"- {name}: {_stage_note(item)}")
    for name, item in context["hooks"].items():
        lines.append(f"- hook.{name}: {_stage_note(item)}")
    # 🆕 审计收口（D）：解析完整性账必须**可见**——未解析的行不是"没有这行数据"，
    # 正文列出原始行，禁止让静默丢弃在交付物里再次隐形。
    tp = context["sections"].get("table_parse") or {}
    parsed, counts = tp.get("parsed") or {}, tp.get("malformed_counts") or {}
    if parsed:
        detail = " / ".join(f"{k} {parsed.get(k, 0)}行"
                            + (f"（未解析 {counts[k]}）" if counts.get(k) else "")
                            for k in parsed)
        lines.append(f"- 表格解析：{detail}。")
    for item in tp.get("malformed") or []:
        # 列数只在"列数不匹配"时才有信息量；取值不可解析时列数相等，写出来是噪音。
        shape = ("列数 %s≠%s " % (item.get("cells"), item.get("header_cells"))
                 if item.get("reason") == "column_count_mismatch" else "")
        lines.append(f"  - ⚠️ 未解析行 [{item.get('section')}] "
                     f"{shape}（{item.get('reason')}）：`{item.get('raw')}`")
    lines += ["", "## 自选股整理追问", "", "同数据日不自动重复整理；如需结合今日盘面处理个别自选，请明确指名。", ""]
    return "\n".join(lines)
