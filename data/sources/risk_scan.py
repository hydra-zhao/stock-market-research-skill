#!/usr/bin/env python3
"""risk_scan.py — 零配额风险负面扫描（立案/处罚/监管函/减持/退市风险）· v7.0.12

事故背景（2026-08-28 航锦科技 000818）：问财配额耗尽日尾盘，000818 被给出突发
触发位并买入，而其 2026-04-04《关于公司收到立案告知书的公告》已挂网近 5 个月——
skill 的风险负面层（监管扫描 search:news / 事件提醒 hithink-event-query / 候选三查）
全部是问财单点，问财一死整层失明，且"用户决定买入前必走诊断"是软规则，尾盘
快节奏下被跳过。东财公告接口实测 15 秒即可命中该公告（零配额免登录）。

本模块 = 风险负面层的零配额降级路，**fail-closed 设计**：
- 主源: 东财公告接口 np-anotice-stock.eastmoney.com（近 2×100 条 ≈1 年+）
- 备源: 巨潮资讯 cninfo（akshare stock_zh_a_disclosure_report_cninfo）
- 全源失败 → [em_risk ERR] + "⚠️ 风险无法核查"手动检查横幅（🚫 禁止当作无负面）
- 有效代码返回 0 条公告 = 源异常（正常 A 股必有定期报告类公告）→ 同样 fail-closed

分级对齐 SKILL.md 负面分级（v6.9.7②）：
🔴严重（一票否决级）= 立案 / 行政处罚 / 事先告知书 / 留置 / 退市风险 / 终止上市
🟠中等（降档级）= 监管函 / 警示函 / 减持（占比未知 → 待核实，禁止直接当轻微）
⚪轻微（标注级）= 问询函 / 关注函

出口硬闸（SKILL.md「风险扫描硬闸」节）：凡产出买入候选/触发位/入池/评级的标的
必过本扫描；个股诊断与 tailscan 候选池已自动接入，mx_xuangu --risk 可选接入。
"""

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.netguard import http_get  # noqa: E402  (v7.2.6 网络出口守卫)

# ---------- 关键词分级（顺序即优先级：严重 > 中等 > 轻微） ----------

SEV_FATAL = ("立案", "行政处罚", "处罚事先告知", "事先告知书", "留置",
             "退市风险", "终止上市")
SEV_WARN = ("监管函", "警示函", "减持")
SEV_MILD = ("问询函", "关注函")

_SEV_ORDER = {"🔴": 0, "🟠": 1, "⚪": 2}

_EM_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_WINDOW_DAYS = 365
_EM_PAGES = 2
_TIMEOUT = 12

MANUAL_CHECK_BANNER = (
    "⚠️ **风险无法核查**（本段 ≠ 无负面，是检查失败）——按 v7.0.12 硬闸：禁止给出"
    "触发位/入池/买入评级，必须先手动检查：\n"
    "1. 巨潮资讯网 cninfo.com.cn → 搜代码 → 立案调查/监管类公告\n"
    "2. 东财个股页「公告」栏 → 近一年标题过一遍\n"
    "3. 同花顺 F10 → 公司大事/风险提示\n"
    "4. MX 搜索「<代码> 立案 处罚 监管函 减持」（v6.9.20 突发新闻验证例外）"
)


def severity(title: str):
    """公告标题 → '🔴'|'🟠'|'⚪'|None（无关标题返回 None）"""
    for k in SEV_FATAL:
        if k in title:
            return "🔴"
    for k in SEV_WARN:
        if k in title:
            return "🟠"
    for k in SEV_MILD:
        if k in title:
            return "⚪"
    return None


def _in_window(date_str: str, today, window_days: int = _WINDOW_DAYS) -> bool:
    """日期在窗口内（无法解析的日期一律保留——fail-closed，宁多报不漏报）"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(date_str))
    if not m:
        return True
    try:
        from datetime import date as _date
        d = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return True
    return (today - d).days <= window_days


# ---------- 数据源（注入点：em=http函数 / cninfo=akshare模块，测试零网络） ----------

def _default_http(url, params):
    r = http_get(url, params=params, timeout=_TIMEOUT,
                 headers={"User-Agent": _UA})
    r.raise_for_status()
    return r.json()


def _fetch_em(code: str, http=None) -> list:
    """东财公告近 2 页×100 条 → [(date 'YYYY-MM-DD', title)]；失败/异常 raise"""
    http = http or _default_http
    out = []
    for page in range(1, _EM_PAGES + 1):
        params = {"sr": -1, "page_size": 100, "page_index": page,
                  "ann_type": "A", "client_source": "web",
                  "stock_list": code, "f_node": 0, "s_node": 0}
        data = http(_EM_URL, params)
        items = (((data or {}).get("data") or {}).get("list")) or []
        out += [(str(it.get("notice_date", ""))[:10], str(it.get("title", "")))
                for it in items if isinstance(it, dict)]
        if len(items) < 100:
            break
    return out


def _fetch_cninfo(code: str, ak=None) -> list:
    """巨潮资讯（akshare）近1年公告 → [(date, title)]；失败/异常 raise"""
    if ak is None:
        import akshare as ak
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=_WINDOW_DAYS + 7)
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=code, market="沪深京",
        start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    if df is None or df.empty:
        raise RuntimeError("cninfo 返回空表")
    tcol = next((c for c in ("公告标题",) if c in df.columns), None)
    dcol = next((c for c in ("公告时间", "公告日期") if c in df.columns), None)
    if tcol is None:
        raise RuntimeError(f"cninfo 列缺失: {list(df.columns)[:6]}")
    out = []
    for _, r in df.iterrows():
        d = str(r[dcol])[:10] if dcol else ""
        out.append((d, str(r[tcol])))
    return out


def scan_code(code: str, em=None, cninfo=None, today=None) -> tuple:
    """单代码扫描 → (hits [(date, title, sev)], source)。

    东财优先、巨潮备源；单源 0 条公告视为该源异常自动换备源（正常 A 股必有
    定期报告类公告）；双源全失败（含双双 0 条）→ RuntimeError（fail-closed）。
    """
    from datetime import date as _date
    today = today or _date.today()
    errors = []
    for name, fn in (("东财", lambda: _fetch_em(code, http=em)),
                     ("巨潮", lambda: _fetch_cninfo(code, ak=cninfo))):
        try:
            rows = fn()
            if not rows:
                raise RuntimeError(f"{name}返回0条公告（正常A股必有定期报告，判源异常）")
            seen, hits = set(), []
            for d, t in rows:
                sev = severity(t)
                if sev and (d, t) not in seen and _in_window(d, today):
                    seen.add((d, t))
                    hits.append((d or "????-??-??", t, sev))
            hits.sort(key=lambda h: (_SEV_ORDER[h[2]], h[0]), reverse=False)
            return hits, name
        except Exception as e:
            errors.append(f"{name}:{type(e).__name__}")
    raise RuntimeError(" | ".join(errors))


# ---------- 渲染 ----------

_CONCLUSION = {"🔴": "🔴 严重负面（一票否决）", "🟠": "🟠 待分级负面（降档级）",
               "⚪": "⚪ 仅轻微（标注级）"}


def _hit_line(h, max_title=44):
    d, t, sev = h
    return f"{d} [{sev}] {t[:max_title]}"


def render_scan(results: dict, failures: dict, sources: dict) -> str:
    """results={code:[hits]}, failures={code:err}, sources={code:源名} → 段落"""
    lines = ["**风险扫描**（v7.0.12 硬闸 · 🔴=一票否决 🟠=降档 ⚪=标注；"
             "窗口≈1年）", "",
             "| 代码 | 结论 | 命中明细 |", "|------|------|------|"]
    for code, hits in results.items():
        if not hits:
            lines.append(f"| {code} | ✅ 近1年无命中 | — |")
            continue
        top = max(hits, key=lambda h: -_SEV_ORDER[h[2]])[2]
        detail = "；".join(_hit_line(h) for h in hits[:5])
        if len(hits) > 5:
            detail += f"；…等{len(hits)}条"
        lines.append(f"| {code} | {_CONCLUSION[top]} | {detail} |")
    for code, err in failures.items():
        lines.append(f"| {code} | ⚠️ 无法核查 | 源失败（{err}）——按硬闸手动检查后再议 |")
    srcs = sorted(set(sources.values()))
    if srcs == ["东财"]:
        src_note = "东财"
    elif "东财" in srcs:
        src_note = "东财→巨潮降级(" + "/".join(srcs) + ")"
    else:
        src_note = "巨潮(" + "/".join(srcs) + ")" if srcs else "无源"
    lines.append("")
    # 🆕 v7.2.13 分母含失败码：旧 len/len 恒等式在有失败码时谎报全量核查
    lines.append(f"_em_risk: {len(results)}/{len(results) + len(failures)} codes · {src_note}公告标题扫描"
                 f"（东财近{_EM_PAGES * 100}条）· 减持占比/立案进展以问财「解禁减持」路"
                 f"或公告原文核实 · 巨潮备源_")
    return "\n".join(lines)


# ---------- 🆕 v7.2.1 fuyao 异动层（第二层补充：当日异动解析榜过风险词；失败静默不阻塞） ----------

_ANOMALY_MEMO = {}   # {date_str: {6位码: hit}} 进程内一次拉取复用（批量扫多码不重复耗 QPS）


def _fuyao_anomaly_hits(codes, today):
    """返回 {code: (date, title, sev)}；无 key/失败/无命中 → {}（补充层永不改判 ok/fail）。"""
    from datetime import date as _date
    today = today or _date.today()
    key = today.strftime("%Y-%m-%d")
    try:
        if key not in _ANOMALY_MEMO:
            import os
            if not (os.environ.get("FUYAO_API_KEY") or os.environ.get("HITHINK_FINANCE_API_KEY")):
                _ANOMALY_MEMO[key] = {}
            else:
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from sources.hithink_runner import anomaly_risk_map
                _ANOMALY_MEMO[key] = anomaly_risk_map(key) or {}
        m = _ANOMALY_MEMO[key]
        return {c: m[c] for c in codes if c in m}
    except Exception:
        return {}


# ---------- dispatch 入口 ----------

def run_risk_scan(query: str, em=None, cninfo=None, today=None) -> tuple:
    """dispatch 入口（kind='em_risk'）：query="000818,600519 ..."（任意分隔符提6位码）。
    返回 (label, body, ok, elapsed, 'em_risk')；ok=False 时 body 带 [em_risk ERR]
    + 手动检查横幅（fail-closed：ERR 永不冒充无负面）。"""
    label = "风险扫描"
    t0 = time.time()
    codes = []
    for c in re.findall(r"(?<!\d)\d{6}(?!\d)", str(query)):
        if c not in codes:
            codes.append(c)
    ok, body = False, ""
    try:
        if not codes:
            raise RuntimeError(f"无有效6位代码: {query!r}")
        results, failures, sources = {}, {}, {}
        with ThreadPoolExecutor(max_workers=min(8, len(codes))) as ex:
            futs = {ex.submit(scan_code, c, em, cninfo, today): c for c in codes}
            for f in as_completed(futs):
                c = futs[f]
                try:
                    hits, src = f.result()
                    results[c], sources[c] = hits, src
                except Exception as e:
                    failures[c] = str(e)[:120]
        if not results and failures:
            raise RuntimeError("；".join(f"{c}: {e}" for c, e in failures.items()))
        # 🆕 v7.2.1 fuyao 异动层交叉（补充第二层：当日异动榜过风险词；与公告源去重）
        anom = _fuyao_anomaly_hits(list(results) + list(failures), today)
        for c, hit in anom.items():
            # Fuyao anomaly is supporting evidence only. It may enrich a code whose
            # official/announcement chain was verified, but can never clear a
            # failure or turn an unverified buy gate into a pass (RISK-002).
            if c in failures:
                continue
            results.setdefault(c, [])
            if not any(hit[1][:24] in h[1] or h[1][:24] in hit[1] for h in results[c]):
                results[c].append(hit)
        body = render_scan(results, failures, sources)
        if anom:
            body += ("\n_+fuyao异动层交叉命中 " + "/".join(sorted(anom))
                     + "（v7.2.1 当日异动解析榜，问财死日第二层；无 key/失败=静默）_")
        ok = True
    except Exception as e:
        ok = False
        body = f"[em_risk ERR] {e}\n\n{MANUAL_CHECK_BANNER}"
    return (label, body, ok, time.time() - t0, "em_risk")


def load_watchlist_codes(base=None):
    """🆕 v7.2.4：最新 output/mx/mx_zixuan_*.csv → [6位码]（名单真相源=MX 接口实拉，
    防手工拼名单把已删标的扫进去——9/2 幽灵名单实测教训）。"""
    import csv
    p_base = Path(base) if base else Path(__file__).resolve().parents[2] / "output" / "mx"
    files = sorted(p_base.glob("mx_zixuan_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        return []
    with open(files[-1], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    idx = next((i for i, h in enumerate(rows[0]) if h.strip() == "代码"), 1)
    out = []
    for r in rows[1:]:
        if len(r) > idx:
            m = re.search(r"(\d{6})", r[idx])
            if m:
                out.append(m.group(1))
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # v7.2.8 GBK 控制台/管道防崩（全 repo CLI 统一形态）
    except Exception:
        pass
    import sys
    # 🆕 审计收口（C）：--help 统一入口（exit 0，零副作用）。此前本文件既无
    # argparse 也无守卫，`--help` 会被当成代码串喂给 run_risk_scan（提不出 6 位码
    # → 打印假 fail-closed 横幅 + exit 2）；`watchlist --help` 更会真读生产自选
    # CSV 并对其整张名单出网扫描。守卫必须在 len(argv)<2 分支之前。
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(__doc__.strip() or "用法见模块头注")
        raise SystemExit(0)
    if len(sys.argv) < 2:
        print("用法: python data/sources/risk_scan.py <代码> [代码...] ｜ "
              "watchlist（扫全部 MX 接口自选；零配额）")
        sys.exit(1)
    args = sys.argv[1:]
    if args[0] == "watchlist":
        codes = load_watchlist_codes()
        if not codes:
            print("[watchlist] 未找到 output/mx/mx_zixuan_*.csv 或无有效代码 → 先拉取 MX 自选名单")
            sys.exit(1)
        print(f"[watchlist] 名单真相源：MX 接口自选 {len(codes)} 只")
        args = codes
    _, body, ok, elapsed, src = run_risk_scan(" ".join(args))
    print(body)
    print(f"\n[{src} {'OK' if ok else 'ERR'} {elapsed:.1f}s]")
    sys.exit(0 if ok else 2)
