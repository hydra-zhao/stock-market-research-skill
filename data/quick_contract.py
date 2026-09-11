"""FINAL-001 shared delivery primitives (no trading decisions)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

# FINAL-001 内部实现版本（manifest 溯源用；不改 schema 主版本语义）
# v7.3.5 1.1→1.2：market 派生指标、holding.quote、swing_summary。
# v7.3.5b 1.2→1.3：relay/mainline/tomorrow deterministic analysis blocks。
SCHEMA_REVISION = "1.3"
RENDERER_VERSION = "1.3"

STAGE_STATUSES = {
    "complete", "reused", "preliminary", "degraded", "unverified",
    "failed", "skipped", "not_applicable",
    # N4：seat_profile 是 seat 状态事实源，FINAL-001 必须原样承载其完整词表，
    # 不得把 incomplete/suspicious/repaired/legacy_unverified 折叠成 unverified。
    "incomplete", "suspicious", "repaired", "failed_to_repair", "legacy_unverified",
}

# N4：seat stage 的交付策略——唯一事实源。gate（quick_delivery）与展示
# （quick_renderer）都读这里，禁止在别处散落 if。
#   allow        —— 允许发布
#   allow_labeled——允许发布，但正文必须显著标注该状态（不是"隐式放行"）
#   window       —— 仅在数据日 17:00 前允许（时间合法性另由 temporal_valid 判定）
#   block        —— 已知缺陷态：阻断 publishable，需先修复/重拉
SEAT_STAGE_POLICY = {
    "complete": "allow",
    "repaired": "allow",
    "preliminary": "window",
    "incomplete": "block",
    "suspicious": "block",
    "failed_to_repair": "block",
    "failed": "block",
    "unverified": "allow_labeled",
    "legacy_unverified": "allow_labeled",
    "degraded": "allow_labeled",
}
SEAT_STAGE_POLICY_DEFAULT = "block"   # 未知状态 fail-closed，不隐式放行
SEAT_STAGE_LABELS = {
    "complete": "完整（正式校验通过）",
    "repaired": "已修复（重拉后正式校验通过）",
    "preliminary": "预抓（未到 17:00 正式窗口）",
    "incomplete": "不完整（交易所缺口/关键字段异常，需重拉全量）",
    "suspicious": "可疑（数量或交易所分布异常，需补拉/人工核验）",
    "failed_to_repair": "修复失败（新数据未通过正式校验）",
    "failed": "失败",
    "unverified": "未验证（旁证不可得）",
    "legacy_unverified": "历史未验证（无席位事实，需 audit --repair）",
    "degraded": "降级",
}


def seat_policy(status: str) -> str:
    """seat 状态 → 交付策略；未知状态按 fail-closed 处理。"""
    return SEAT_STAGE_POLICY.get(status, SEAT_STAGE_POLICY_DEFAULT)


def seat_label(status: str) -> str:
    return SEAT_STAGE_LABELS.get(status, f"未知状态（{status}）")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: dict) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def reused_source_errors(item: dict) -> list[str]:
    """N8：``reused`` 必须能证明"复用的是哪份成功结果"——路径存在且 hash 一致。

    只记录 source_time 不足以证明来源未被改写；reused 不阻断发布的前提之一
    就是来源文件/hash 可验证。
    """
    path = Path(str(item.get("source_path") or ""))
    if not item.get("source_path") or not path.is_file():
        return ["reused source file missing"]
    if sha256_file(path) != item.get("source_sha256"):
        return ["reused source hash mismatch"]
    return []


def stage_temporal_valid(stage_id: str, status: str, now: datetime, *, data_date: str | None = None) -> bool:
    """Machine-readable time legality as a pure function.

    Seat preliminary is legal only before 17:00 on its data day. Other stage
    degradation policy is validated separately by the delivery validator.
    """
    if status not in STAGE_STATUSES:
        return False
    if stage_id == "seat" and status == "preliminary":
        normalized_date = str(data_date or "").replace("/", "-")
        if len(normalized_date) == 8 and normalized_date.isdigit():
            normalized_date = f"{normalized_date[:4]}-{normalized_date[4:6]}-{normalized_date[6:]}"
        return now.date().isoformat() == normalized_date and now.hour < 17
    return True


def stage(stage_id: str, status: str, now: datetime, *, data_date: str | None = None,
          source_time=None, error=None, source_path=None, source_sha256=None) -> dict:
    return {
        "stage_id": stage_id,
        "status": status,
        "source_time": source_time,
        "temporal_valid": stage_temporal_valid(stage_id, status, now, data_date=data_date),
        "error": error,
        "source_path": source_path,
        "source_sha256": source_sha256,
    }
