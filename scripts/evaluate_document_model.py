#!/usr/bin/env python3
"""Produce a machine-readable independent document-model evaluation report.

Input is a JSON object with immutable artifact/dataset identifiers and a
``records`` list. Each record requires ``true_type``, ``predicted_type``,
``confidence``, and ``subject_id``; optional ``subgroup`` and ``latency_ms``
fields enable robustness and operational summaries. Use ``unknown`` for OOD
ground truth or rejected predictions.
"""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

KNOWN_CLASSES = (
    "business_permit",
    "business_photo",
    "income_proof",
    "invalid",
    "proof_of_address",
    "selfie_with_id",
    "valid_id",
)


def _safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _wilson_interval(successes, total, z=1.959963984540054):
    if not total:
        return [0.0, 0.0]
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def evaluate_records(
    payload,
    *,
    minimum_per_class=30,
    minimum_macro_f1=0.80,
    maximum_ece=0.10,
    minimum_ood_recall=0.80,
):
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    confusion = defaultdict(Counter)
    counts = Counter()
    subjects = defaultdict(set)
    subgroup_results = defaultdict(lambda: [0, 0])
    calibration_bins = defaultdict(lambda: [0, 0.0, 0])
    latencies = []
    issues = []

    for index, record in enumerate(records):
        true_type = str(record.get("true_type", ""))
        predicted_type = str(record.get("predicted_type", ""))
        subject_id = str(record.get("subject_id", "")).strip()
        if true_type not in {*KNOWN_CLASSES, "unknown"}:
            issues.append(f"record_{index}:true_type_invalid")
            continue
        if predicted_type not in {*KNOWN_CLASSES, "unknown"}:
            issues.append(f"record_{index}:predicted_type_invalid")
            continue
        if not subject_id:
            issues.append(f"record_{index}:subject_id_missing")
            continue
        try:
            confidence = float(record["confidence"])
        except (KeyError, TypeError, ValueError):
            issues.append(f"record_{index}:confidence_invalid")
            continue
        if not 0 <= confidence <= 1:
            issues.append(f"record_{index}:confidence_invalid")
            continue

        counts[true_type] += 1
        confusion[true_type][predicted_type] += 1
        subjects[subject_id].add(true_type)
        correct = true_type == predicted_type
        subgroup = str(record.get("subgroup", "unspecified"))
        subgroup_results[subgroup][0] += int(correct)
        subgroup_results[subgroup][1] += 1
        bin_index = min(9, int(confidence * 10))
        calibration_bins[bin_index][0] += int(correct)
        calibration_bins[bin_index][1] += confidence
        calibration_bins[bin_index][2] += 1
        if record.get("latency_ms") is not None:
            latencies.append(float(record["latency_ms"]))

    for subject_id, labels in subjects.items():
        if len(labels) > 1:
            issues.append(f"subject_label_conflict:{subject_id}")

    per_class = {}
    for class_name in KNOWN_CLASSES:
        true_positive = confusion[class_name][class_name]
        false_negative = sum(confusion[class_name].values()) - true_positive
        false_positive = sum(
            confusion[other][class_name]
            for other in {*KNOWN_CLASSES, "unknown"}
            if other != class_name
        )
        precision = _safe_div(true_positive, true_positive + false_positive)
        recall = _safe_div(true_positive, true_positive + false_negative)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_class[class_name] = {
            "count": counts[class_name],
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "recall_95ci": _wilson_interval(true_positive, counts[class_name]),
        }
        if counts[class_name] < int(minimum_per_class):
            issues.append(f"class_below_minimum:{class_name}:{counts[class_name]}")

    macro_f1 = sum(item["f1"] for item in per_class.values()) / len(per_class)
    total = sum(item[2] for item in calibration_bins.values())
    ece = (
        sum(
            count
            / total
            * abs(_safe_div(correct, count) - _safe_div(confidence_sum, count))
            for correct, confidence_sum, count in calibration_bins.values()
        )
        if total
        else 1.0
    )
    unknown_total = counts["unknown"]
    unknown_detected = confusion["unknown"]["unknown"]
    ood_recall = _safe_div(unknown_detected, unknown_total)
    false_rejects = sum(confusion[name]["unknown"] for name in KNOWN_CLASSES)
    known_total = sum(counts[name] for name in KNOWN_CLASSES)
    false_accepts = sum(
        count
        for predicted, count in confusion["unknown"].items()
        if predicted != "unknown"
    )

    if unknown_total < int(minimum_per_class):
        issues.append(f"ood_below_minimum:{unknown_total}")
    if macro_f1 < float(minimum_macro_f1):
        issues.append("macro_f1_below_gate")
    if ece > float(maximum_ece):
        issues.append("calibration_error_above_gate")
    if ood_recall < float(minimum_ood_recall):
        issues.append("ood_recall_below_gate")

    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    return {
        "schema_version": 1,
        "artifact_sha256": payload.get("artifact_sha256"),
        "dataset_manifest_sha256": payload.get("dataset_manifest_sha256"),
        "preprocessing_version": payload.get("preprocessing_version"),
        "threshold_policy_version": payload.get("threshold_policy_version"),
        "record_count": len(records),
        "subject_count": len(subjects),
        "counts": dict(counts),
        "per_class": per_class,
        "macro_f1": macro_f1,
        "expected_calibration_error": ece,
        "ood_recall": ood_recall,
        "false_accept_rate": _safe_div(false_accepts, unknown_total),
        "false_reject_rate": _safe_div(false_rejects, known_total),
        "subgroups": {
            name: {"accuracy": _safe_div(values[0], values[1]), "count": values[1]}
            for name, values in sorted(subgroup_results.items())
        },
        "latency_ms": {
            "count": len(sorted_latencies),
            "p95": sorted_latencies[p95_index] if sorted_latencies else None,
        },
        "confusion_matrix": {
            actual: dict(predicted) for actual, predicted in confusion.items()
        },
        "gates": {
            "minimum_per_class": int(minimum_per_class),
            "minimum_macro_f1": float(minimum_macro_f1),
            "maximum_ece": float(maximum_ece),
            "minimum_ood_recall": float(minimum_ood_recall),
        },
        "issues": sorted(set(issues)),
        "passes_gates": not issues,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-per-class", type=int, default=30)
    parser.add_argument("--minimum-macro-f1", type=float, default=0.80)
    parser.add_argument("--maximum-ece", type=float, default=0.10)
    parser.add_argument("--minimum-ood-recall", type=float, default=0.80)
    args = parser.parse_args(argv)
    raw = args.predictions.read_bytes()
    payload = json.loads(raw)
    report = evaluate_records(
        payload,
        minimum_per_class=max(1, args.minimum_per_class),
        minimum_macro_f1=args.minimum_macro_f1,
        maximum_ece=args.maximum_ece,
        minimum_ood_recall=args.minimum_ood_recall,
    )
    report["predictions_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passes_gates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
