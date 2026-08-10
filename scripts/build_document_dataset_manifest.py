#!/usr/bin/env python3
"""Build a deterministic subject-grouped dataset manifest, dry-run by default.

The provenance input is a JSON object keyed by dataset-relative image path.
Every entry must provide ``source``, ``license_or_consent_basis``,
``anonymized: true``, and ``subject_id``. Files are never moved or modified.
Use ``--apply`` only after reviewing the printed manifest.
"""

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_CLASSES = (
    "business_permit",
    "business_photo",
    "income_proof",
    "invalid",
    "proof_of_address",
    "selfie_with_id",
    "valid_id",
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _subject_split(subject_id, seed):
    bucket = (
        int(
            hashlib.sha256(f"{seed}:{subject_id}".encode("utf-8")).hexdigest()[:8],
            16,
        )
        % 100
    )
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "validation"
    return "holdout"


def build_manifest(data_root, provenance, *, seed="document-dataset-v1"):
    data_root = Path(data_root).resolve()
    entries = []
    issues = []
    subject_assignments = {}
    for class_name in EXPECTED_CLASSES:
        class_dir = data_root / class_name
        if not class_dir.is_dir():
            issues.append(f"class_directory_missing:{class_name}")
            continue
        for path in sorted(class_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            relative_path = path.relative_to(data_root).as_posix()
            metadata = provenance.get(relative_path)
            if not isinstance(metadata, dict):
                issues.append(f"provenance_missing:{relative_path}")
                continue
            required = (
                "source",
                "license_or_consent_basis",
                "subject_id",
            )
            missing = [field for field in required if not metadata.get(field)]
            if missing or metadata.get("anonymized") is not True:
                issues.append(f"provenance_incomplete:{relative_path}")
                continue
            subject_id = str(metadata["subject_id"])
            split = subject_assignments.setdefault(
                subject_id, _subject_split(subject_id, seed)
            )
            entries.append(
                {
                    "path": relative_path,
                    "class": class_name,
                    "source": metadata["source"],
                    "license_or_consent_basis": metadata["license_or_consent_basis"],
                    "anonymized": True,
                    "subject_id": subject_id,
                    "split": split,
                    "sha256": _sha256(path),
                }
            )
    return {
        "schema_version": 1,
        "seed": seed,
        "split_policy": {"train": 70, "validation": 15, "holdout": 15},
        "entries": entries,
        "issues": sorted(set(issues)),
        "ready": not issues,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", default="document-dataset-v1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    manifest = build_manifest(args.data_root, provenance, seed=args.seed)
    rendered = json.dumps(manifest, indent=2) + "\n"
    print(rendered, end="")
    if not manifest["ready"]:
        return 1
    if args.apply:
        output = args.output or args.data_root / "dataset_manifest.json"
        output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
