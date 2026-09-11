#!/usr/bin/env python3
"""lint_review.py — 复盘输出结构校验器（D2修复·2026-08-22 审计）

背景：v6.9.29 自检收口清单靠"发送前心里打勾"，执行者仍是会忘的模型——
漏梯队表/漏追问/漏首板归类三次事故同一根因。本模块把清单机械化：
模型发送复盘前跑一遍，缺章节即报错退出，"心里打勾"变程序断言。

用法：
    python lint_review.py <review.md>            # auto：按工件判定 quick/full
    python lint_review.py <review.md> --mode full
    type review.md | python lint_review.py -     # stdin
退出码：0=通过；1=缺章节；2=文件/参数错误

🆕 审计收口（C）模式契约：`--mode auto` 为默认。旧默认值是 quick，而全仓
文档（SKILL.md §3/§6、references/market-review.md、current-rules.md 的
OUT-001/HOOK-011）都只教 `lint_review.py <file>` —— 等于**完整复盘的 9 个
full 专属章节（含第十章日记心得/第十一章数据采集自检）默认完全不校验**。
auto 用工件自身信号判定；无判别信号时取 **full**（full 是 quick 的严格超集，
fail-closed 只多报不漏报）。
"""
import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 章节判定语义（🆕 v6.9.37 修正）：每个检查项由若干「关键词组」组成，组间 AND、
# 组内 OR——任一组完全无命中即判缺失。修复两点：
#   ①完整模式误用快速模式TL;DR头（"## ⚡ 快速复盘 TL;DR"）——完整模板标题为"## 一句话结论"
#   ②"持仓"类单关键词全匹配过严——完整模板第八章标题为"对当前持仓的影响"
QUICK_CHECKS = [
    ("①TL;DR一句话结论", [["## ⚡ 快速复盘 TL;DR", "## 一句话结论"], ["一句话结论"]]),
    ("②关键信号（四人裁决）", [["四人裁决"], ["退神"], ["涅槃"]]),
    ("③核心数据", [["核心数据", "涨停"]]),
    ("④聪明资金一句话（期指+ETF各一句）", [["聪明资金"], ["期指"], ["ETF"]]),
    ("⑤连板梯队表+断板名单+解读", [["连板梯队", "梯队表"], ["断板名单"], ["一句话解读", "解读"]]),
    ("⑥首板题材归类", [["首板题材归类"]]),
    ("⑦持仓对照", [["持仓对照", "对当前持仓的影响", "持仓"]]),
    ("⑧整理追问", [["自选股整理", "整理追问", "是否需要结合今日盘面"]]),
    ("⑨趋势波段候选（候选/无/未验证）", [["趋势波段候选"],
                                        ["合适标的", "深查清单", "无合格标的", "保持空池", "未验证"]]),
]

FULL_EXTRA = [
    ("第一章·宏观政策信号→板块传导（十维）", [["宏观政策信号", "宏观"], ["传导"]]),
    # 🆕 审计收口（C）编号修正：这两项内容都属第二章「聪明资金监测」，旧标"第九章"
    # 与第九章「总结」撞号（第九章正是下面的总结项），纯展示名，不影响判定。
    # 🆕 审计收口（C）：OUT-001 原文点名"聪明资金含**牛熊线与十年历史定位**"，
    # 此前 lint 对"牛熊"零 key（两处历史成稿都写了，属漏检而非误报）。
    ("第二章·聪明资金监测", [["聪明资金", "期指", "国家队ETF"], ["牛熊"]]),
    ("第二章·期指风格与现期联动", [["主要作用风格", "IH/IF/IC/IM"],
                                ["现期联动", "现期联动未验证"]]),
    ("第三章·市场情绪量化", [["市场情绪量化", "冰点期", "涨停比", "封板率"]]),
    ("第四章·主线案例类比（有匹配或明确不适用）",
     [["案例库类比", "题材波类比", "未确认主线，无案例匹配", "主线未确认，案例匹配不适用"]]),
    # 🆕 审计收口（C）覆盖率补漏：OUT-001 声明的 11 章里，「五、板块资金」与
    # 「九、总结」此前**没有任何 lint key**，完整复盘缺这两章不会被拦。
    ("第五章·板块资金", [["板块资金"]]),
    ("第六章·商品与国债", [["商品与国债", "商品", "国债"]]),
    # 第七章（四人裁决）/第八章（对当前持仓的影响）已由 QUICK_CHECKS 的
    # ②/⑦ 覆盖（full 模式是 quick 超集），不重复登记以免同一缺失报两次。
    # 🆕 I 轮（2026-09-10）：旧 key 只认模板字面「九、总结」，而实盘成稿的标题是
    # 「## 第九章·总结与明日关注」（output/full-review-20260907.md 实测）→ 真写了的
    # 第九章被判缺失（误报）。改为两种合法标题体并列，仍要求编号+章名同现。
    ("第九章·总结", [["九、总结", "第九章·总结", "第九章 总结"]]),
    ("第十章·日记心得（缺失=bug，模板自检明令）", [["日记心得"]]),
    ("第十一章·数据采集自检（缺失=bug，模板自检明令）", [["数据采集自检"]]),
    # v6.9.44 审计修复：催化/明日关注归属"操作建议/总结"章，原误标"第十一章"
    ("操作建议/总结·催化与明日关注", [["明日关注", "明天关注", "关注要点"]]),
    # 🆕 审计收口（C）覆盖率补漏：模板 :107 明令"每次追加美股指数ETF观察（仅QQQ/SPY）"。
    ("条件附录·美股指数ETF观察（QQQ/SPY，每次必附）",
     [["美股指数ETF"], ["QQQ", "SPY"]]),
]

# 🆕 审计收口（C）：条件附录里的"每月首次周期题材定位"是**月度条件项**，
# lint 无日期上下文，设为提示项（不参与退出码），只提醒不要漏。
FULL_ADVISORY = [
    ("条件附录·月度周期题材定位（每月首次）",
     [["周期题材定位", "月度周期定位", "cycle all", "monthly_cycle"]]),
]

# 🆕 I 轮（2026-09-10）：盘中豁免收窄到**现行规则**真正豁免的两项。旧集合（审查修复④
# 2026-08-22）按已废止的 v6.9.21 口径把 ②四人裁决/⑦持仓对照 也算作"盘中停用"——
# 现行口径逐项对照：
#   · ⑧整理追问：OUT-004 明令「盘中快照不追加整理追问」→ 豁免。
#   · ⑨趋势波段候选：market-review §3 条件附录「每次**非盘中**复盘必须追加」→ 豁免。
#   · ②关键信号（四人裁决）/⑦持仓对照：ECO-007 允许盘中作**临时**生态判断，OUT-003
#     要求标注"盘中临时、收盘待确认"；且 FINAL-001 canonical renderer 无论盘中与否
#     都输出这两段（quick_renderer.render）。豁免=对真缺段漏报 → 不再豁免。
INTRADAY_EXEMPT = {"⑧整理追问", "⑨趋势波段候选（候选/无/未验证）"}


# 🆕 审计收口（C）：auto 判定信号。判别顺序=正文 full 信号 → 正文 quick 信号 →
# 文件名 quick 提示 → 兜底 full。正文优先于文件名（改名不改变内容语义）。
FULL_TEXT_MARKERS = ("## 详细数据", "（11章）", "（11 章）", "宏观政策信号",
                     "市场情绪量化", "商品与国债")
QUICK_TEXT_MARKERS = ("⚡ 快速复盘 TL;DR",)
QUICK_NAME_HINTS = ("quick-review", "quick-snapshot")


def detect_mode(text: str, path: str | None = None) -> tuple[str, str]:
    """auto 模式判定 → ``(mode, 依据说明)``。

    full 是 quick 的严格超集，无判别信号时取 **full**（fail-closed，只多报不漏报）。
    注意「数据采集自检」**不能**做判别信号：快速复盘也输出它
    （``quick_renderer`` 的"数据采集自检"段），用它判别会把 full 误判成 quick。
    """
    if any(m in text for m in FULL_TEXT_MARKERS):
        return "full", "正文含完整复盘专属章节"
    if any(m in text for m in QUICK_TEXT_MARKERS):
        return "quick", "正文含快速复盘 TL;DR 头"
    name = Path(path).name if path and path != "-" else ""
    if any(h in name for h in QUICK_NAME_HINTS):
        return "quick", f"文件名 {name} 属快速复盘工件"
    return "full", "无判别信号，fail-closed 按完整模式校验"


def advisory_missing(text: str, mode: str) -> list[str]:
    """月度/条件性附录的提示项（不参与退出码）。"""
    if mode != "full":
        return []
    out = []
    for name, groups in FULL_ADVISORY:
        if any(not any(k in text for k in g) for g in groups):
            out.append(name)
    return out


def lint(text: str, mode: str = "quick"):
    """返回 (missing: list[str], total: int, skipped: list[str])。

    组间AND、组内OR；任一组零命中判缺失。
    🆕 盘中豁免：文本含"盘中快照"标记时，INTRADAY_EXEMPT 章节自动跳过并计入 skipped
    （⏭️ 展示），不计入 missing。"""
    checks = list(QUICK_CHECKS)
    if mode == "full":
        # 第九章与催化项已在 FULL_EXTRA；避免重复注册
        checks += [c for c in FULL_EXTRA if c[0] not in {n for n, _ in checks}]
    intraday = "盘中快照" in text
    missing, skipped = [], []
    for name, groups in checks:
        if intraday and name in INTRADAY_EXEMPT:
            skipped.append(name)
            continue
        dead_groups = []
        for g in groups:
            if not any(k in text for k in g):
                dead_groups.append(g)
        if dead_groups:
            flat = sorted({k for g in dead_groups for k in g})
            missing.append(f"{name} —— 以下关键词组均未命中: {flat}")
    return missing, len(checks), skipped


FINAL_REQUIRED_HEADINGS = {
    "TL;DR": ("快速复盘 TL;DR", "一句话结论"),
    "四人裁决": ("关键信号", "四人裁决"),
    "核心数据": ("核心数据",),
    "聪明资金": ("聪明资金",),
    "梯队断板": ("连板梯队", "断板名单"),
    "首板题材": ("首板题材归类",),
    "持仓对照": ("持仓对照", "对当前持仓的影响"),
    "趋势波段": ("趋势波段候选",),
    "数据自检": ("数据采集自检",),
    "整理追问": ("自选股整理追问", "整理追问"),
}


def _h2_sections(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.M))
    return [(m.group(1).strip(), text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip())
            for i, m in enumerate(matches)]


def lint_delivery(text: str, context: dict | None = None) -> list[str]:
    """Strict FINAL-001 Markdown structure and context consistency lint."""
    errors = []
    sections = _h2_sections(text)
    for label, aliases in FINAL_REQUIRED_HEADINGS.items():
        matches = [(h, body) for h, body in sections if any(a in h for a in aliases)]
        if not matches:
            errors.append(f"missing H2 section: {label}")
        elif not any(body.strip() for _, body in matches):
            errors.append(f"empty H2 section: {label}")
    holdings = [(h, b) for h, b in sections if "持仓对照" in h or "对当前持仓的影响" in h]
    if not holdings:
        errors.append("期指持仓等通用文本不能代替持仓对照 H2")
    if context:
        m = context.get("market", {})
        core = next((b for h, b in sections if "核心数据" in h), "")
        for key, label in (("limit_up", "涨停"), ("limit_down", "跌停"), ("bomb", "炸板")):
            if str(m.get(key)) not in core or label not in core:
                errors.append(f"context mismatch: {label}={m.get(key)}")
        action = context.get("actions", {}).get("ultra_relay", {})
        if action.get("allowed") is False and action.get("max_new_position_pct") not in (0, 0.0, None):
            errors.append("ultra_relay action conflict")
    return errors


def main():
    ap = argparse.ArgumentParser(description="复盘输出结构校验器")
    ap.add_argument("file", help="复盘 markdown 文件路径，或 '-' 读 stdin")
    ap.add_argument("--mode", choices=["auto", "quick", "full"], default="auto",
                    help="校验模式；auto（默认）按工件自动判定，歧义取 full")
    args = ap.parse_args()

    if args.file == "-":
        text = sys.stdin.read()
    else:
        p = Path(args.file)
        if not p.exists():
            print(f"[ERR] 文件不存在: {p}", file=sys.stderr)
            sys.exit(2)
        text = p.read_text(encoding="utf-8", errors="replace")

    if not text.strip():
        print("[ERR] 空内容", file=sys.stderr)
        sys.exit(2)

    if args.mode == "auto":
        mode, why = detect_mode(text, args.file)
    else:
        mode, why = args.mode, "显式指定"
    missing, total, skipped = lint(text, mode)
    passed = total - len(missing)
    print(f"== 复盘结构校验（{mode} 模式 / {why}）== {passed}/{total} 通过")
    for s in skipped:
        print(f"  ⏭️ 盘中豁免：{s}（v6.9.21 盘中降级，不适用）")
    for m in missing:
        print(f"  ❌ 缺失：{m}")
    for a in advisory_missing(text, mode):
        print(f"  ℹ️ 条件项未命中（不阻塞）：{a}")
    if missing:
        print("\n🔴 不通过：补全缺失章节后再发送（缺失=bug，见 SKILL.md v6.9.29 清单）")
        sys.exit(1)
    print("🟢 全部强制章节在位，可发送")


if __name__ == "__main__":
    main()
