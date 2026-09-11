# -*- coding: utf-8 -*-
"""common/timing.py — 数据源/步骤耗时摘要（v7.2.13d P2·工程基线）。

两件事：
①机器可读单行摘要 `TIMING|{json}`——quick_fetch / market_fetch（数据拉取阶段
  耗时，非端到端总耗时）/ hooks（编排全部步骤耗时，emit 于所有步骤完成后），
  上层（lint_review / agent / cron 日志分析）可直接 grep 解析；
②持续记录 output/timing/source_log.jsonl（每次运行 append 每个数据源一行，
  含成功/失败状态），percentiles()/summary_lines() 出各数据源 p50/p95——
  慢源劣化有数据可查，不追求虚高总耗时数字，只回答"哪个源在变慢"。

密闭性：pytest 环境下（_skip_disk()）只打印不落盘——测试零仓库状态污染
（v7.2.13a 曾专项清理 output 下测试散落物，同教训）。
"""
import json
import os
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
TIMING_LOG = _HERE.parent.parent / "output" / "timing" / "source_log.jsonl"


def _skip_disk() -> bool:
    """落盘闸：pytest 环境只打印不落盘（测试零仓库状态污染）。
    独立函数形态便于测试以真实临时文件验证 emit→percentiles 全链（monkeypatch 之）。"""
    return "PYTEST_CURRENT_TEST" in os.environ


def record(kind: str, source: str, seconds: float, ok: bool = True) -> None:
    """单条耗时留档（jsonl 追加；落盘失败静默——计时绝不反噬业务路径）。"""
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind,
           "source": source, "seconds": round(float(seconds), 3), "ok": bool(ok)}
    if _skip_disk():
        return
    try:
        TIMING_LOG.parent.mkdir(parents=True, exist_ok=True)
        with TIMING_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def emit(kind: str, stages: dict, total: float | None = None) -> str:
    """打印并返回 `TIMING|{json}` 单行摘要；stages 各项同时 record 留档。

    stages: {数据源/步骤名: 秒} 或 {步骤名: (秒, ok)}（v7.2.13d 一轮回修 P1-5：
    失败步骤必须以 ok=False 留档与呈现，不得混入成功统计）。total 缺省=各项
    秒数之和；汇总 ok=所有被调度阶段均成功。TIMING 载荷含各阶段状态。
    """
    norm: dict = {}
    all_ok = True
    sec_sum = 0.0
    for name, v in stages.items():
        if isinstance(v, tuple):
            sec, ok = float(v[0]), bool(v[1])
        else:
            sec, ok = float(v), True
        norm[name] = {"seconds": round(sec, 3), "ok": ok}
        sec_sum += sec
        all_ok = all_ok and ok
    total = round(sec_sum, 3) if total is None else round(total, 3)
    payload = {"kind": kind, "total": total, "ok": all_ok, "stages": norm}
    line = "TIMING|" + json.dumps(payload, ensure_ascii=False)
    print(line)
    for name, item in norm.items():
        record(kind, name, item["seconds"], ok=item["ok"])
    record(kind, "_total", total, ok=all_ok)
    return line


def _pct(sorted_vals: list, q: float) -> float:
    """nearest-rank 分位（ceil(q*n) 序号，1 基）：n=10 的 p50=第5小、p95=第10小。"""
    if not sorted_vals:
        return 0.0
    import math
    idx = max(0, min(len(sorted_vals) - 1, math.ceil(q * len(sorted_vals)) - 1))
    return sorted_vals[idx]


def _tail_records(sources, kind: str | None, limit: int) -> dict:
    """🆕 v7.2.13e P03：一次流式扫文件，对每个 source 维护"最近 limit 条"有界
    队列（成功与失败同窗计数——选样范围=该 source 最近 limit 条记录，不局限
    成败）。旧实现先 read_text 全文件再切行、limit 只作用于切片不作用于筛选
    结果（limit=2 实测统计 n=8），且 summary_lines 每源重复全量读一遍。"""
    from collections import deque
    deques: dict = {s: deque(maxlen=max(1, int(limit))) for s in sources}
    if not TIMING_LOG.exists():
        return deques
    try:
        with TIMING_LOG.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue            # 坏行跳过，不崩
                src = r.get("source")
                if src in deques and not src.startswith("_"):
                    if kind and r.get("kind") != kind:
                        continue
                    deques[src].append(r)
    except OSError:
        pass
    return deques


def _stats_from(records: list) -> dict:
    vals = sorted(float(r.get("seconds", 0.0)) for r in records
                  if r.get("ok", True))
    fail = sum(1 for r in records if not r.get("ok", True))
    if not vals:
        return {"n": 0, "p50": None, "p95": None, "fail": fail}
    return {"n": len(vals), "p50": round(_pct(vals, 0.5), 2),
            "p95": round(_pct(vals, 0.95), 2), "fail": fail}


def percentiles(source: str, kind: str | None = None,
                limit: int = 2000) -> dict:
    """某数据源最近 limit 条记录 → {n, p50, p95, fail}；无成功样本但有失败
    返回 n=0/fail=N（全败显式可见），完全无记录返回 {}。"""
    dq = _tail_records([source], kind, limit).get(source)
    if dq is None or not dq:
        return {}
    return _stats_from(list(dq))


def summary_lines(sources, kind: str | None = None, limit: int = 2000) -> list:
    """各数据源一行 p50/p95 概览（一次文件扫描；二轮回修 P2-2：全部失败的
    数据源显式浮出）。"""
    deques = _tail_records(list(sources), kind, limit)
    out = []
    for s in sources:
        dq = deques.get(s)
        if not dq:
            continue
        p = _stats_from(list(dq))
        if p["n"]:
            out.append(f"  {s}: n={p['n']} p50={p['p50']}s p95={p['p95']}s"
                       + (f" fail={p['fail']}" if p["fail"] else ""))
        elif p["fail"]:
            out.append(f"  {s}: n=0 fail={p['fail']}，暂无成功耗时样本")
    return out
