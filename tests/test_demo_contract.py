# -*- coding: utf-8 -*-
"""离线 demo 端到端契约测试（公开版新增）。

证明：无网络、无 API key、无私有数据时，合成快照可以走完
FINAL-001 交付链（context → render → lint → manifest → verify）
并得到 publishable=true 的可交付正文。
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
for _p in ("data", "demo"):
    if str(_HERE / _p) not in sys.path:
        sys.path.insert(0, str(_HERE / _p))

from run_demo import DATA_DATE, NOW, build_snapshot
from quick_contract import sha256_file
from quick_delivery import build_delivery, verify_delivery


def test_snapshot_is_deterministic(tmp_path):
    a, b = build_snapshot(), build_snapshot()
    assert a == b and "示例" in a and "18/18" in a


def test_full_delivery_chain_is_publishable(tmp_path):
    snapshot = tmp_path / f"quick-snapshot-{DATA_DATE.replace('-', '')}-201500.md"
    snapshot.write_text(build_snapshot(), encoding="utf-8")
    context_path, review_path, manifest_path, manifest = build_delivery(
        snapshot, output_dir=tmp_path, now=NOW)
    assert manifest["publishable"] is True, manifest["errors"]
    assert review_path.name == f"quick-review-{DATA_DATE.replace('-', '')}.md"
    persisted = json.loads(context_path.read_text(encoding="utf-8"))
    assert persisted["source_snapshot"]["sha256"] == sha256_file(snapshot)
    # 正文是确定性渲染：重跑一致
    first = review_path.read_text(encoding="utf-8")
    build_delivery(snapshot, output_dir=tmp_path, now=NOW)
    assert review_path.read_text(encoding="utf-8") == first
    # 交付前复核
    assert verify_delivery(manifest_path, now=NOW) == []


def test_verify_detects_tampered_artifact(tmp_path):
    snapshot = tmp_path / f"quick-snapshot-{DATA_DATE.replace('-', '')}-201500.md"
    snapshot.write_text(build_snapshot(), encoding="utf-8")
    _, review_path, manifest_path, _ = build_delivery(
        snapshot, output_dir=tmp_path, now=NOW)
    review_path.write_text(
        review_path.read_text(encoding="utf-8").replace("快速复盘", "被篡改"),
        encoding="utf-8")
    errors = verify_delivery(manifest_path, now=NOW)
    assert any("hash mismatch" in e for e in errors)
