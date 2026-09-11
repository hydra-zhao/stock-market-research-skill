"""FINAL-001 final pipeline: context -> render -> lint -> manifest -> verify."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from lint_review import lint_delivery
from quick_context import ROOT, build_context, validate_context
from quick_contract import (RENDERER_VERSION, SCHEMA_REVISION, atomic_write_json,
                            atomic_write_text, reused_source_errors, seat_policy,
                            sha256_file, stage_temporal_valid)
from quick_renderer import render

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MANIFEST_VERSION = "1.0"
LINT_VERSION = "1.0"


def _snapshot_for_run(output_dir: Path, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    final = output_dir / f"quick-snapshot-{stamp}.md"
    tmp = output_dir / f".{final.name}.collecting"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "data" / "round1_v2.py"), "quick", "--out", str(tmp)],
        cwd=ROOT, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"quick collection failed rc={result.returncode}")
    tmp.replace(final)
    return final


def _critical_stage_errors(context: dict, *, now: datetime | None = None) -> list[str]:
    now = now or datetime.now().astimezone()
    data_date = context["data_date"]
    errors = []
    for name, item in context["stages"].items():
        if not stage_temporal_valid(item["stage_id"], item["status"], now, data_date=data_date):
            errors.append(f"stage {name} temporal invalid")
    collect = context["stages"]["collect"]
    if collect["status"] == "failed":
        errors.append("collect failed")
    for name, item in context["stages"].items():
        # N8：reused 不阻断发布，但必须证明"复用自哪份可验证的成功结果"。
        if item.get("status") == "reused":
            errors += [f"stage {name} {e}" for e in reused_source_errors(item)]
    # N4：seat 交付策略是唯一事实源；已知缺陷态阻断 publishable。
    seat = context["stages"].get("seat")
    if seat and seat_policy(str(seat.get("status"))) == "block":
        errors.append(f"seat stage status={seat.get('status')} blocked by policy")
    for name, item in context["hooks"].items():
        if not stage_temporal_valid(item["stage_id"], item["status"], now, data_date=data_date):
            errors.append(f"hook {name} temporal invalid")
    return errors


def build_delivery(snapshot: Path, *, output_dir: Path | None = None, now: datetime | None = None,
                   positions_path: Path | None = None, root: Path = ROOT) -> tuple[Path, Path, Path, dict]:
    now = now or datetime.now().astimezone()
    output_dir = Path(output_dir or root / "output" / "reviews")
    context = build_context(snapshot, now=now, positions_path=positions_path, root=root)
    context_errors = validate_context(context)
    date8 = context["data_date"].replace("-", "")
    context_path = output_dir / f"quick-context-{date8}.json"
    review_path = output_dir / f"quick-review-{date8}.md"
    manifest_path = output_dir / f"delivery-manifest-{date8}.json"
    atomic_write_json(context_path, context)
    persisted = json.loads(context_path.read_text(encoding="utf-8"))
    context_errors += validate_context(persisted)
    markdown = render(persisted)
    atomic_write_text(review_path, markdown)
    artifact_hash = sha256_file(review_path)  # only after atomic replace
    lint_errors = lint_delivery(review_path.read_text(encoding="utf-8"), persisted)
    gate_errors = _critical_stage_errors(persisted, now=now)
    publishable = not context_errors and not lint_errors and not gate_errors
    manifest = {
        "contract": "FINAL-001", "manifest_version": MANIFEST_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "context_path": str(context_path.resolve()), "context_sha256": sha256_file(context_path),
        "renderer_version": RENDERER_VERSION, "schema_revision": SCHEMA_REVISION,
        "artifact_path": str(review_path.resolve()),
        "artifact_sha256": artifact_hash, "lint_version": LINT_VERSION,
        "lint_exit_code": 0 if not lint_errors else 1,
        "errors": context_errors + lint_errors + gate_errors,
        "publishable": publishable,
    }
    atomic_write_json(manifest_path, manifest)
    verify_errors = verify_delivery(manifest_path, now=now)
    if verify_errors:
        manifest["publishable"] = False
        manifest["errors"] += verify_errors
        atomic_write_json(manifest_path, manifest)
    return context_path, review_path, manifest_path, manifest


def verify_delivery(manifest_path: Path, *, now: datetime | None = None) -> list[str]:
    now = now or datetime.now().astimezone()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    errors = []
    context_path = Path(manifest.get("context_path", ""))
    artifact_path = Path(manifest.get("artifact_path", ""))
    if not context_path.is_file() or sha256_file(context_path) != manifest.get("context_sha256"):
        errors.append("context hash mismatch")
    if not artifact_path.is_file() or sha256_file(artifact_path) != manifest.get("artifact_sha256"):
        errors.append("artifact hash mismatch (TOCTOU)")
    if manifest.get("lint_exit_code") != 0:
        errors.append("lint failed")
    if manifest.get("contract") == "FINAL-001" and context_path.is_file() and artifact_path.is_file():
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
            errors += validate_context(context)
            source = context.get("source_snapshot", {})
            source_path = Path(source.get("path", ""))
            if not source_path.is_file() or sha256_file(source_path) != source.get("sha256"):
                errors.append("source snapshot hash mismatch")
            errors += lint_delivery(artifact_path.read_text(encoding="utf-8"), context)
            errors += _critical_stage_errors(context, now=now)
        except Exception as exc:
            errors.append(f"delivery revalidation failed: {type(exc).__name__}: {exc}")
    if manifest.get("publishable") is not True:
        errors.append("manifest publishable is not true")
    return errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FINAL-001 Quick Review final delivery pipeline")
    ap.add_argument("--final", action="store_true", help="required delivery-contract acknowledgement")
    ap.add_argument("--snapshot", type=Path, help="existing non-deliverable quick snapshot")
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--positions", type=Path)
    ap.add_argument("--now", help="ISO datetime override for deterministic tests/audits")
    ap.add_argument("--verify", type=Path, help="recheck manifest hashes before delivery")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    if args.verify:
        errors = verify_delivery(args.verify, now=now)
        print("publishable" if not errors else "NOT publishable: " + "; ".join(errors))
        return 0 if not errors else 1
    if not args.final:
        ap.error("--final is required; snapshots are never publishable")
    out = args.output_dir or ROOT / "output" / "reviews"
    snapshot = args.snapshot or _snapshot_for_run(Path(out), now)
    context_path, review_path, manifest_path, manifest = build_delivery(
        snapshot, output_dir=out, now=now, positions_path=args.positions,
    )
    print(f"context={context_path}")
    print(f"artifact={review_path}")
    print(f"manifest={manifest_path}")
    print(f"publishable={str(manifest['publishable']).lower()}")
    return 0 if manifest["publishable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
