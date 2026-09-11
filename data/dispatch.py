#!/usr/bin/env python3
"""dispatch.py — 任务调度器，协调各数据源 runner"""

import re
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 同会话内存缓存：避免同一轮分析中重复拉取相同数据
# key: (kind, query, limit), value: (timestamp, result_tuple)
_RESULT_CACHE = {}
_CACHE_TTL_SECONDS = 300  # 5 分钟

# MX 后端（mkapi2，mx/xg 同源）并发闸门：实测并行>2 时服务端繁忙返回畸形
# payload 的概率显著上升（2026-07-29 四路并行连续复现），限 2 路并发保稳定
_MX_SEM = threading.Semaphore(2)

# 资讯/公告类任务：输出前自动校验日期（旧闻标注，防止旧闻冒充新催化）
# 🆕 v7.0.12 +风险扫描（立案/处罚类命中需显龄——4/4 立案 vs 8/28 买入的教训）
_NEWS_LABELS = {"个股资讯", "公告原文", "板块新闻", "监管扫描", "ETF资讯", "ETF公告",
                "风险扫描"}
_NEWS_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def annotate_news_dates(body: str, today=None) -> str:
    """资讯/公告段日期自动校验：>7天标注🕐旧闻，>30天标注🕐🕐历史。

    背景：mx数据源可靠性协议的血泪教训——搜索结果里的旧闻被误读为新催化。
    对每行找到的第一个 yyyy-MM-dd 日期计算与今天的天数差，超期即在行尾追加标注。
    """
    today = today or datetime.now().date()
    out = []
    for line in body.split("\n"):
        m = _NEWS_DATE_RE.search(line)
        if m:
            try:
                d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
                age = (today - d).days
                if age > 30:
                    line += " 🕐🕐历史(>30天)"
                elif age > 7:
                    line += " 🕐旧闻(>7天)"
            except ValueError:
                pass
        out.append(line)
    return "\n".join(out)


def _cache_key(t):
    """为 task 生成缓存 key。task 格式: (label, kind, query, [limit])。
    🆕 v7.2.13e F02：键不含 label（同查询跨模式复用），但缓存值在命中时重绑
    当前任务 label——展示身份与缓存数据解耦。"""
    label, kind, query = t[0], t[1], t[2]
    limit = t[3] if len(t) > 3 else 5
    return (kind, query, limit)


def _rebind_label(t, result):
    """缓存命中/复用时把结果的展示 label 换成当前任务的（数据体不动）。"""
    if isinstance(result, tuple) and len(result) == 5:
        return (t[0],) + result[1:]
    return result


def _src_of_kind(kind: str) -> str:
    """异常路径无法从 runner 拿到 src——按 kind 前缀推导（与 runner 返回的
    src 分组口径一致：iw/mx/ak/ths/em_risk；未知 kind 落自身名）。"""
    if kind.startswith("iw:"):
        return "iw"
    if kind in ("mx", "xg"):
        return "mx"
    if kind in ("ak", "ak_etf", "ak_zt", "ak_ff"):
        return "ak"
    if kind in ("ths_zt", "ths_kline"):
        return "ths"
    if kind == "provider":
        return "provider"
    return kind


def _get_cached(t):
    key = _cache_key(t)
    entry = _RESULT_CACHE.get(key)
    if not entry:
        return None
    ts, result = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        del _RESULT_CACHE[key]
        return None
    return _rebind_label(t, result)


def _set_cached(t, result):
    # 期指当日尚未发布时 runner 会回退前一交易日。该结果可展示，但不能按
    # “当日请求”缓存 5 分钟，否则 16 点后的再次核验仍会命中昨日数据。
    if t[1] == "ak" and isinstance(result, tuple) and len(result) == 5 and result[2]:
        requested = str(t[2] or "").replace("-", "")
        body = str(result[1])
        m = re.search(r"期指持仓变化\s+(\d{4})-(\d{2})-(\d{2})", body)
        returned = "".join(m.groups()) if m else ""
        if requested and returned and requested != returned:
            return
    _RESULT_CACHE[_cache_key(t)] = (time.time(), result)


def dispatch(tasks, mode_label):
    """并行执行 tasks，每个 task 是 (label, kind, query, [limit])。
    kind: 'mx' | 'ak' | 'iw:<skill_id>' | '<skill_id>'
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sources.iwencai_runner import run_iw
    from sources.mx_runner import run_mx
    from sources.xg_runner import run_xg
    from sources.cffex import run_akshare_cffex

    results, t0 = [], time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"===== ROUND1 v2 {mode_label} {now} =====", f"问财+MX | {len(tasks)} 并行\n"]

    # 先处理缓存命中
    # 🆕 v7.2.13e F02：按任务序号保存结果——同批重复 label 不再被 dict 静默覆盖
    cached_results = {}   # index -> result 5元组
    tasks_to_run = []
    for i, t in enumerate(tasks):
        cached = _get_cached(t)
        if cached is not None:
            cached_results[i] = cached
            try:
                from common.timing import record as _timing_record
                _timing_record("task_fetch", f"{mode_label}:cache:{t[0]}", 0.0, True)
            except Exception:
                pass
        else:
            tasks_to_run.append((i, t))

    def run(t):
        label, kind, query = t[0], t[1], t[2]
        limit = t[3] if len(t) > 3 else 5
        if kind == "mx":
            with _MX_SEM:
                return run_mx(label, query, limit)
        if kind == "xg":
            with _MX_SEM:
                return run_xg(label, query, limit)
        if kind == "ak":
            return run_akshare_cffex(query if query else None)
        if kind == "ak_etf":
            # 🆕 国家队ETF 问财路失败（配额/限流）→ AKShare 交易所份额降级（sources/etf_ak.py）
            from sources.etf_ak import run_akshare_etf
            return run_akshare_etf()
        if kind == "ak_zt":
            # 🆕 接力情绪四路问财失败（配额/限流）→ AKShare 东财股池降级（sources/zt_pool_ak.py）
            from sources.zt_pool_ak import run_akshare_ztpool
            return run_akshare_ztpool(query)
        if kind == "ths_zt":
            # 🆕 v7.0.9 情绪五路问财失败 → 同花顺涨停行情 dataapi 降级（sources/ths_limitup.py）
            from sources.ths_limitup import run_ths_limitup
            return run_ths_limitup(query)
        if kind == "ths_kline":
            # 🆕 v7.0.9 历史K线路问财失败 → 同花顺行情 K线降级（sources/ths_line.py）
            from sources.ths_line import run_ths_kline
            return run_ths_kline(query)
        if kind == "ak_ff":
            # 🆕 v7.0.9 板块资金路问财失败 → 同花顺资金流降级（sources/ths_fundflow.py）
            from sources.ths_fundflow import run_ths_fundflow
            return run_ths_fundflow(query)
        if kind == "em_risk":
            # 🆕 v7.0.12 风险负面扫描硬闸（零配额 fail-closed：东财公告→巨潮双源）
            from sources.risk_scan import run_risk_scan
            return run_risk_scan(query)
        if kind == "provider":
            from providers.runner import run_provider
            return run_provider(label, query)
        if kind.startswith("iw:"):
            return run_iw(label, kind.split(":", 1)[1], query, limit)
        return run_iw(label, kind, query, limit)

    # 提高并发：IO 密集型任务，worker 数可以大于 CPU 核数
    max_workers = min(16, max(4, len(tasks_to_run)))
    idx_task = dict(tasks_to_run)          # 序号→任务（同批同元组各自独立）
    started_at = {i: time.time() for i in idx_task}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(run, t): i for i, t in tasks_to_run}
        for f in as_completed(futures):
            i = futures[f]
            t = idx_task[i]
            elapsed_exc = time.time() - started_at.get(i, time.time())
            try:
                result = f.result()
            except Exception as e:  # noqa: BLE001 🆕 v7.2.13 单路炸不陪葬整轮——
                # 旧实现 f.result() 裸抛，一路 KeyError（实弹通道=cffex chg 列缺失）
                # 丢弃全部已完成路结果。
                # 🆕 v7.2.13e F01：异常结果保持标准五元组（label/body/ok/elapsed/src）
                # ——旧 {"error":..} 形状在组装层按 5 元组解包=ValueError 击穿整轮，
                # 且被缓存后同一失败任务再次调用同样崩。ERR body 同构各路失败降级，
                # err_code 正则不匹配时组装层落 "ERR"，状态自检表可见。
                label, kind = t[0], t[1]
                result = (label,
                          f"[dispatch ERR] {type(e).__name__}: {e}\n"
                          f"⚠️ 该路任务在调度器内异常退出（非数据源返回失败）——结果缺失，"
                          f"勿按'无数据'解读，可单独重跑该路核实",
                          False, elapsed_exc, _src_of_kind(kind))
            _set_cached(t, result)
            cached_results[i] = result
            try:
                from common.timing import record as _timing_record
                _timing_record("task_fetch", f"{mode_label}:{t[0]}", elapsed_exc,
                               bool(isinstance(result, tuple) and len(result) == 5 and result[2]))
            except Exception:
                pass

    # 按原始任务顺序组装结果
    results = [cached_results[i] for i in range(len(tasks))]

    cnt = {"iw": [0, 0], "mx": [0, 0], "ak": [0, 0], "ths": [0, 0]}
    status_rows = []
    for i, (label, body, ok, elapsed, src) in enumerate(results):
        if ok and label in _NEWS_LABELS:
            body = annotate_news_dates(body)
        s = "OK" if ok else "ERR"
        lines.append(f"\n--- [{i + 1}/{len(tasks)}] {label} [{src}] {s} ({elapsed:.1f}s) ---\n")
        lines.append(body)
        c = cnt.setdefault(src, [0, 0])
        c[1] += 1
        c[0] += int(ok)

        # 提取错误类型（如 [iw TIMEOUT]、[mx AUTH]、[ak ERR]、[xg ERR]、[ths ERR]、[em_risk ERR]）
        # v6.9.44 审计清理：删除循环内 import re（模块顶部 line 4 已有）
        err_code = "OK"
        if not ok:
            m = re.search(r"\[(?:iw|mx|ak|xg|ths|em_risk)\s+(\w+)\]", body)
            err_code = m.group(1) if m else "ERR"
        status_rows.append((label, src.upper(), err_code, f"{elapsed:.1f}s"))

    # 数据源状态自检表
    lines.append("\n--- 数据源状态自检 ---")
    lines.append("| 任务 | 来源 | 状态 | 耗时 |")
    lines.append("|------|:--:|:--:|------|")
    for label, src, err_code, elapsed in status_rows:
        lines.append(f"| {label} | {src} | {err_code} | {elapsed} |")

    # v6.9.44 审计修复：汇总行动态拼接全部源计数（旧硬编码 iw/mx/ak 三键，
    # xg 源〔MX连板天梯/MX炸板股〕的成功率不进自检汇总）
    _src_sum = " ".join(f"{k}:{v[0]}/{v[1]}" for k, v in cnt.items())
    lines.append(f"\n===== {_src_sum} total:{time.time() - t0:.1f}s =====")
    return "\n".join(lines)
