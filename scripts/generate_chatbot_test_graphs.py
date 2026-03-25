#!/usr/bin/env python3
"""
Generate chatbot test result graphs from a pytest JUnit XML report.

Usage:
  python scripts/generate_chatbot_test_graphs.py \
    --xml documents/ml/reports/ai_evaluation/chatbot_pytest_results.xml
"""
from __future__ import annotations

import argparse
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt


DEFAULT_XML = "documents/ml/reports/ai_evaluation/chatbot_pytest_results.xml"
DEFAULT_OUT_DIR = "documents/ml/reports/ai_evaluation"


def _parse_xml(xml_path: Path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    cases = []
    for testcase in root.findall(".//testcase"):
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        duration = float(testcase.attrib.get("time", "0") or 0.0)
        failed = testcase.find("failure") is not None or testcase.find("error") is not None
        skipped = testcase.find("skipped") is not None
        status = "failed" if failed else ("skipped" if skipped else "passed")
        cases.append(
            {
                "classname": classname,
                "name": name,
                "duration": duration,
                "status": status,
            }
        )
    return cases


def _extract_feature_group(test_name: str) -> str:
    # Convert names like "test_chat_returns_500_on_empty_ai_response"
    # to a compact feature-ish label.
    stem = re.sub(r"^test_", "", test_name)
    tokens = stem.split("_")
    if len(tokens) <= 2:
        return stem
    return "_".join(tokens[:2])


def _extract_endpoint_group(test_name: str) -> str:
    if "streaming" in test_name:
        return "chat_stream"
    if "history" in test_name:
        return "history"
    if "suggestions" in test_name:
        return "suggestions"
    if "education" in test_name:
        return "education"
    if "faq" in test_name:
        return "faqs"
    if "status" in test_name:
        return "ai_status"
    if "chat_" in test_name:
        return "chat"
    return "other"


def _extract_http_group(test_name: str) -> str:
    if "history_get" in test_name:
        return "GET"
    if "history_delete" in test_name:
        return "DELETE"
    if any(k in test_name for k in ["suggestions", "education", "faq", "status"]):
        return "GET"
    return "POST"


def _save_plot(path: Path):
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved: {path}")
    plt.close()


def generate_graphs(cases, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    status_counts = Counter(case["status"] for case in cases)
    status_counts.setdefault("passed", 0)
    status_counts.setdefault("failed", 0)
    status_counts.setdefault("skipped", 0)

    # Graph 1: Pass/Fail/Skip
    plt.figure(figsize=(7, 5))
    labels = ["passed", "failed", "skipped"]
    values = [status_counts[l] for l in labels]
    colors = ["#2ecc71", "#e74c3c", "#f1c40f"]
    bars = plt.bar(labels, values, color=colors, edgecolor="black")
    for bar, value in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width() / 2, value + 0.05, str(value), ha="center")
    plt.title("Chatbot Test Outcomes")
    plt.ylabel("Number of Tests")
    _save_plot(out_dir / "chatbot_test_outcomes.png")

    # Graph 2: Outcome pie
    plt.figure(figsize=(7, 7))
    pie_labels = ["passed", "failed", "skipped"]
    pie_values = [status_counts[l] for l in pie_labels]
    pie_colors = ["#2ecc71", "#e74c3c", "#f1c40f"]
    plt.pie(
        pie_values,
        labels=pie_labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=pie_colors,
        wedgeprops={"edgecolor": "black"},
    )
    plt.title("Chatbot Test Outcome Share")
    _save_plot(out_dir / "chatbot_test_outcomes_pie.png")

    # Graph 3: Duration per test (sorted)
    sorted_cases = sorted(cases, key=lambda c: c["duration"], reverse=True)
    plt.figure(figsize=(12, 5))
    x = list(range(len(sorted_cases)))
    y = [c["duration"] * 1000 for c in sorted_cases]
    plt.bar(x, y, color="#3498db", edgecolor="black")
    plt.title("Chatbot Test Duration per Test Case")
    plt.xlabel("Test Cases (sorted by duration)")
    plt.ylabel("Duration (ms)")
    _save_plot(out_dir / "chatbot_test_durations.png")

    # Graph 4: Duration histogram
    durations_ms = [c["duration"] * 1000 for c in cases]
    plt.figure(figsize=(10, 5))
    bins = min(12, max(4, int(math.sqrt(len(durations_ms)))))
    plt.hist(durations_ms, bins=bins, color="#1abc9c", edgecolor="black")
    plt.title("Chatbot Test Duration Distribution")
    plt.xlabel("Duration (ms)")
    plt.ylabel("Number of Tests")
    _save_plot(out_dir / "chatbot_test_duration_histogram.png")

    # Graph 5: Top slowest test cases
    top_n = min(10, len(sorted_cases))
    top_cases = sorted_cases[:top_n]
    plt.figure(figsize=(12, 6))
    labels = [c["name"] for c in top_cases]
    values = [c["duration"] * 1000 for c in top_cases]
    plt.barh(labels[::-1], values[::-1], color="#e67e22", edgecolor="black")
    plt.title(f"Top {top_n} Slowest Chatbot Tests")
    plt.xlabel("Duration (ms)")
    _save_plot(out_dir / "chatbot_test_top_slowest.png")

    # Graph 6: Feature-group coverage distribution
    groups = Counter(_extract_feature_group(c["name"]) for c in cases)
    ordered_groups = sorted(groups.items(), key=lambda t: t[1], reverse=True)
    plt.figure(figsize=(12, 6))
    labels = [k for k, _ in ordered_groups]
    values = [v for _, v in ordered_groups]
    plt.bar(labels, values, color="#9b59b6", edgecolor="black")
    plt.title("Chatbot Test Distribution by Feature Group")
    plt.xlabel("Feature Group (derived from test name)")
    plt.ylabel("Number of Tests")
    plt.xticks(rotation=45, ha="right")
    _save_plot(out_dir / "chatbot_test_feature_groups.png")

    # Graph 7: Endpoint-group coverage distribution
    endpoint_groups = Counter(_extract_endpoint_group(c["name"]) for c in cases)
    ordered = sorted(endpoint_groups.items(), key=lambda t: t[1], reverse=True)
    plt.figure(figsize=(10, 5))
    labels = [k for k, _ in ordered]
    values = [v for _, v in ordered]
    plt.bar(labels, values, color="#8e44ad", edgecolor="black")
    plt.title("Chatbot Test Distribution by Endpoint Group")
    plt.xlabel("Endpoint Group")
    plt.ylabel("Number of Tests")
    plt.xticks(rotation=20, ha="right")
    _save_plot(out_dir / "chatbot_test_endpoint_groups.png")

    # Graph 8: HTTP-method distribution
    methods = Counter(_extract_http_group(c["name"]) for c in cases)
    method_labels = ["GET", "POST", "DELETE"]
    method_values = [methods.get(m, 0) for m in method_labels]
    plt.figure(figsize=(8, 5))
    plt.bar(method_labels, method_values, color="#34495e", edgecolor="black")
    plt.title("Chatbot Test Distribution by HTTP Method")
    plt.xlabel("HTTP Method")
    plt.ylabel("Number of Tests")
    _save_plot(out_dir / "chatbot_test_http_methods.png")


def run():
    parser = argparse.ArgumentParser(description="Generate chatbot pytest result graphs")
    parser.add_argument("--xml", default=DEFAULT_XML, help="Path to pytest JUnit XML file")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory for graphs")
    args = parser.parse_args()

    xml_path = Path(args.xml)
    if not xml_path.exists():
        raise SystemExit(f"JUnit XML not found: {xml_path}")

    cases = _parse_xml(xml_path)
    if not cases:
        raise SystemExit("No testcases found in XML.")

    out_dir = Path(args.out_dir)
    generate_graphs(cases, out_dir)

    passed = sum(1 for c in cases if c["status"] == "passed")
    failed = sum(1 for c in cases if c["status"] == "failed")
    skipped = sum(1 for c in cases if c["status"] == "skipped")
    total = len(cases)
    accuracy = (passed / total * 100) if total else 0.0
    print(
        f"Summary: total={total}, passed={passed}, failed={failed}, "
        f"skipped={skipped}, pass_rate={accuracy:.1f}%"
    )


if __name__ == "__main__":
    run()
