"""Canonical前复权可用性判定。

``adjust=qfq`` 只表示响应中出现了前复权字段；只有完整覆盖率达到
``pattern_registration.QFQ_COVERAGE_MIN`` 才能用于需要连续前复权序列的
统计或前向收益计算。
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from . import pattern_registration as reg


def is_qfq_usable(payload: Mapping[str, Any] | None = None,
                  metadata: Mapping[str, Any] | None = None,
                  *, min_coverage: float | None = None) -> tuple[bool, str | None]:
    """返回 ``(可用, 原因)``，未知覆盖率一律 fail-closed。

    ``payload`` 与 ``metadata`` 分开传入是为了兼容旧 Provider；coverage
    优先取 metadata，再取 payload。``adjust`` 仅作为口径标识，不能替代
    coverage 完整性证据。
    """
    payload = payload or {}
    metadata = metadata or {}
    adjust = metadata.get("adjust_method") or payload.get("adjust_method")
    if adjust is None:
        adjust = payload.get("adjust")
    if str(adjust).lower() != "qfq":
        return False, f"adjust_method_not_qfq:{adjust}"
    coverage = metadata.get("qfq_coverage")
    if coverage is None:
        coverage = payload.get("qfq_coverage")
    try:
        coverage_f = float(str(coverage))
    except (TypeError, ValueError):
        return False, "qfq_coverage_unverified"
    if not math.isfinite(coverage_f) or coverage_f < 0.0 or coverage_f > 1.0:
        return False, "qfq_coverage_invalid"
    required = reg.QFQ_COVERAGE_MIN if min_coverage is None else float(min_coverage)
    if coverage_f + 1e-9 < required:
        return False, f"qfq_coverage_insufficient:{coverage_f:.4f}"
    return True, None
