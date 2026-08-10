#!/usr/bin/env python3
"""Fail-closed document dataset validation with a machine-readable report.

The checker reads only the explicitly selected dataset directory. It never
uploads samples or changes them. A sidecar manifest is required so images with
unknown provenance, consent/license, anonymization, subject grouping, or split
assignment cannot silently enter training.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

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
REQUIRED_METADATA = (
    "source",
    "license_or_consent_basis",
    "anonymized",
    "subject_id",
    "split",
    "sha256",
)
ALLOWED_SPLITS = {"train", "validation", "holdout"}
MIN_SIZE = (224, 224)
MIN_SAMPLES_PER_CLASS = 30


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"manifest_invalid:{type(exc).__name__}"]
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {}, ["manifest_entries_missing"]
    by_path = {}
    issues = []
    for entry in entries:
        relative_path = str(entry.get("path", "")).strip()
        if not relative_path or relative_path in by_path:
            issues.append("manifest_path_missing_or_duplicate")
            continue
        by_path[relative_path] = entry
    return by_path, issues


def validate_dataset(data_root, manifest_path, *, min_samples=MIN_SAMPLES_PER_CLASS):
    """Return a report; ``ready`` is false for every unsafe dataset condition."""
    data_root = Path(data_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest, issues = _load_manifest(manifest_path)
    counts = Counter()
    split_counts = defaultdict(Counter)
    hash_paths = defaultdict(list)
    subject_splits = defaultdict(set)
    files_seen = set()

    for class_name in EXPECTED_CLASSES:
        class_dir = data_root / class_name
        if not class_dir.is_dir():
            issues.append(f"class_directory_missing:{class_name}")
            continue
        image_paths = sorted(
            path
            for path in class_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
        counts[class_name] = len(image_paths)
        if len(image_paths) < int(min_samples):
            issues.append(
                f"class_below_minimum:{class_name}:{len(image_paths)}:{min_samples}"
            )

        for image_path in image_paths:
            relative_path = image_path.relative_to(data_root).as_posix()
            files_seen.add(relative_path)
            try:
                with Image.open(image_path) as image:
                    image.verify()
                with Image.open(image_path) as image:
                    width, height = image.size
                if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
                    issues.append(f"image_undersized:{relative_path}:{width}x{height}")
            except Exception as exc:  # noqa: BLE001 - report only exception class
                issues.append(f"image_corrupt:{relative_path}:{type(exc).__name__}")
                continue

            digest = _sha256(image_path)
            hash_paths[digest].append(relative_path)
            metadata = manifest.get(relative_path)
            if not metadata:
                issues.append(f"provenance_missing:{relative_path}")
                continue
            for field in REQUIRED_METADATA:
                if metadata.get(field) in (None, ""):
                    issues.append(f"metadata_missing:{relative_path}:{field}")
            if metadata.get("sha256") != digest:
                issues.append(f"manifest_hash_mismatch:{relative_path}")
            if metadata.get("anonymized") is not True:
                issues.append(f"anonymization_unapproved:{relative_path}")
            split = metadata.get("split")
            if split not in ALLOWED_SPLITS:
                issues.append(f"split_invalid:{relative_path}")
            else:
                split_counts[split][class_name] += 1
                subject_id = str(metadata.get("subject_id", "")).strip()
                if subject_id:
                    subject_splits[subject_id].add(split)

    for digest, paths in hash_paths.items():
        if len(paths) > 1:
            issues.append(f"exact_duplicate:{digest}:{'|'.join(paths)}")
    for subject_id, splits in subject_splits.items():
        if len(splits) > 1:
            issues.append(
                f"subject_cross_split:{subject_id}:{'|'.join(sorted(splits))}"
            )
    for extra_path in sorted(set(manifest) - files_seen):
        issues.append(f"manifest_file_missing:{extra_path}")

    unique_issues = sorted(set(issues))
    return {
        "schema_version": 1,
        "ready": not unique_issues,
        "data_root": str(data_root),
        "manifest": str(manifest_path),
        "minimum_samples_per_class": int(min_samples),
        "counts": dict(counts),
        "split_counts": {
            split: dict(class_counts)
            for split, class_counts in sorted(split_counts.items())
        },
        "file_count": len(files_seen),
        "issues": unique_issues,
    }


def main(argv=None):
    project_root = Path(__file__).resolve().parent.parent
    default_root = project_root / "documents" / "ml" / "training_data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_root)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--minimum-per-class", type=int, default=MIN_SAMPLES_PER_CLASS)
    args = parser.parse_args(argv)
    manifest = args.manifest or args.data_root / "dataset_manifest.json"
    report_path = args.report or args.data_root / "dataset_validation_report.json"
    report = validate_dataset(
        args.data_root,
        manifest,
        min_samples=max(1, args.minimum_per_class),
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
