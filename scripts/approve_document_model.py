#!/usr/bin/env python3
"""Dry-run-by-default approval gate for a document classifier registry entry."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def approval_check(config, report, artifact_path):
    issues = []
    artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if config.get("artifact_sha256") != artifact_hash:
        issues.append("artifact_hash_mismatch")
    if report.get("artifact_sha256") != artifact_hash:
        issues.append("evaluation_artifact_mismatch")
    if not report.get("passes_gates"):
        issues.append("evaluation_gates_failed")
    for field in (
        "dataset_manifest_sha256",
        "preprocessing_version",
        "threshold_policy_version",
    ):
        if not config.get(field) or config.get(field) != report.get(field):
            issues.append(f"evaluation_{field}_mismatch")
    if not config.get("rollback_target"):
        issues.append("rollback_target_missing")
    return sorted(set(issues))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--approved-by")
    parser.add_argument("--rollback-target")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.rollback_target:
        config["rollback_target"] = args.rollback_target.strip()
    report = json.loads(args.evaluation.read_text(encoding="utf-8"))
    issues = approval_check(config, report, args.artifact)
    result = {"eligible": not issues, "apply": args.apply, "issues": issues}
    print(json.dumps(result, indent=2))
    if issues:
        return 1
    if not args.apply:
        return 0
    if not str(args.approved_by or "").strip():
        parser.error("--approved-by is required with --apply")
    config.update(
        {
            "approval_status": "approved",
            "approved_by": args.approved_by.strip(),
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "deployed_at": None,
            "evaluation_report_sha256": hashlib.sha256(
                args.evaluation.read_bytes()
            ).hexdigest(),
        }
    )
    args.config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
