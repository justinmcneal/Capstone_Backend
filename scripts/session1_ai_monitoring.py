#!/usr/bin/env python3
"""Session 1 AI monitoring helper for MSME Pathways backend.

Collects timing evidence for 3 AI functions:
1) POST /api/ai/chat/
2) POST /api/loans/pre-qualify/
3) GET AI support endpoints (/api/ai/status/, /api/ai/suggestions/, /api/ai/history/)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Tuple

import requests


@dataclass
class RunResult:
    case: str
    elapsed_ms: float
    status_code: int
    ok: bool
    extra_ms: float | None = None


def timed_request(
    method: str,
    url: str,
    headers: dict,
    *,
    payload: dict | None = None,
    params: dict | None = None,
    timeout: int = 60,
) -> Tuple[RunResult, dict | None]:
    start = time.perf_counter()
    resp = requests.request(method, url, headers=headers, json=payload, params=params, timeout=timeout)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    body = None
    try:
        body = resp.json()
    except Exception:
        body = None

    extra_ms = None
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and isinstance(data.get("response_time_ms"), (int, float)):
            extra_ms = float(data["response_time_ms"])

    result = RunResult(
        case="",
        elapsed_ms=elapsed_ms,
        status_code=resp.status_code,
        ok=(200 <= resp.status_code < 300),
        extra_ms=extra_ms,
    )
    return result, body


def summarize(results: List[RunResult]) -> Tuple[float, float, float, int]:
    values = [r.elapsed_ms for r in results]
    return (statistics.mean(values), min(values), max(values), len(values))


def print_section(title: str, results: List[RunResult]) -> bool:
    ok_rows = [r for r in results if r.ok]
    failed_rows = [r for r in results if not r.ok]

    print(title)
    print("-" * 78)
    print(f"{'Case':35} {'Avg(ms)':>10} {'Min(ms)':>10} {'Max(ms)':>10} {'Runs':>8}")
    print("-" * 78)

    grouped: dict[str, List[RunResult]] = {}
    for r in ok_rows:
        grouped.setdefault(r.case, []).append(r)

    for case, rows in grouped.items():
        cavg, cmn, cmx, cruns = summarize(rows)
        print(f"{case:35} {cavg:10.2f} {cmn:10.2f} {cmx:10.2f} {cruns:8d}")

    print("-" * 78)
    if ok_rows:
        avg, mn, mx, runs = summarize(ok_rows)
        print(f"{'OVERALL':35} {avg:10.2f} {mn:10.2f} {mx:10.2f} {runs:8d}")
    else:
        print(f"{'OVERALL':35} {'N/A':>10} {'N/A':>10} {'N/A':>10} {0:8d}")
        print("No successful responses recorded for this function.")

    if failed_rows:
        code_counts = Counter(r.status_code for r in failed_rows)
        code_summary = ", ".join(f"{code}:{count}" for code, count in sorted(code_counts.items()))
        print(f"Failed runs: {len(failed_rows)} ({code_summary})")

    print()
    return bool(ok_rows)


def benchmark_chat(base_url: str, headers: dict, prompts: Iterable[str], repeats: int) -> List[RunResult]:
    url = f"{base_url}/api/ai/chat/"
    conversation_id = str(uuid.uuid4())
    rows: List[RunResult] = []

    for prompt in prompts:
        case = prompt[:30].replace("\n", " ").strip() or "chat_case"
        for _ in range(repeats):
            payload = {
                "message": prompt,
                "language": "en",
                "conversation_id": conversation_id,
            }
            result, body = timed_request("POST", url, headers, payload=payload)
            result.case = case
            rows.append(result)
            if not result.ok:
                print(f"[WARN] Chat failed case='{case}' status={result.status_code} body={body}")
    return rows


def benchmark_prequal(
    base_url: str,
    headers: dict,
    base_payload: dict,
    amounts: Iterable[float],
    repeats: int,
) -> List[RunResult]:
    url = f"{base_url}/api/loans/pre-qualify/"
    rows: List[RunResult] = []

    for amount in amounts:
        case = f"amount_{int(amount)}"
        for _ in range(repeats):
            payload = dict(base_payload)
            payload["amount"] = amount
            result, body = timed_request("POST", url, headers, payload=payload)
            result.case = case
            rows.append(result)
            if not result.ok:
                print(f"[WARN] Pre-qualify failed case='{case}' status={result.status_code} body={body}")
    return rows


def benchmark_ai_api_calls(base_url: str, headers: dict, repeats: int) -> List[RunResult]:
    targets = [
        ("status_get", f"{base_url}/api/ai/status/", None),
        ("suggestions_get", f"{base_url}/api/ai/suggestions/", {"language": "en"}),
        ("history_get", f"{base_url}/api/ai/history/", {"page": 1, "limit": 20}),
    ]

    rows: List[RunResult] = []
    for case, url, params in targets:
        for _ in range(repeats):
            result, body = timed_request("GET", url, headers, params=params)
            result.case = case
            rows.append(result)
            if not result.ok:
                print(f"[WARN] API call failed case='{case}' status={result.status_code} body={body}")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Session 1 AI monitoring evidence collector")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--token", required=True, help="Customer access token (JWT)")
    parser.add_argument(
        "--prequal-base-json",
        required=True,
        help="Path to JSON payload template for /api/loans/pre-qualify/ (without amount)",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Runs per case")
    parser.add_argument(
        "--prequal-amounts",
        default="10000,20000,30000",
        help="Comma-separated amounts for pre-qualify cases",
    )
    parser.add_argument(
        "--only",
        choices=["all", "chat", "prequal", "api"],
        default="all",
        help="Run only one section (default: all)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        with open(args.prequal_base_json, "r", encoding="utf-8") as f:
            prequal_base = json.load(f)
    except Exception as exc:
        print(f"Failed to read --prequal-base-json: {exc}")
        return 1

    try:
        amounts = [float(x.strip()) for x in args.prequal_amounts.split(",") if x.strip()]
    except ValueError:
        print("Invalid --prequal-amounts. Example: 10000,20000,30000")
        return 1

    token = (args.token or "").strip()
    if not token:
        print("Missing --token value.")
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    chat_prompts = [
        "What are the basic requirements to apply for a loan?",
        "Explain loan interest in simple terms for small business owners.",
        "What should I improve if my pre-qualification score is low?",
    ]

    print("Session 1: Prototype Monitoring (AI Track)")
    print()

    if args.only in {"all", "chat"}:
        chat_rows = benchmark_chat(args.base_url.rstrip("/"), headers, chat_prompts, args.repeats)
        chat_ok = print_section("Function 1: AI Chat (POST /api/ai/chat/)", chat_rows)
        if not chat_ok and all(r.status_code in {401, 403} for r in chat_rows):
            print("Authentication/authorization failed for Function 1. Use a fresh valid customer access token.")
            return 1

    if args.only in {"all", "prequal"}:
        prequal_rows = benchmark_prequal(
            args.base_url.rstrip("/"), headers, prequal_base, amounts, args.repeats
        )
        prequal_ok = print_section("Function 2: AI Pre-Qualify (POST /api/loans/pre-qualify/)", prequal_rows)
        if not prequal_ok and all(r.status_code in {401, 403} for r in prequal_rows):
            print("Authentication/authorization failed for Function 2. Use a fresh valid customer access token.")
            return 1
        if not prequal_ok and any(r.status_code == 429 for r in prequal_rows):
            print("Pre-qualify is throttled (429). This endpoint allows limited requests per user per hour.")
            print("Wait for throttle window reset, restart local dev server cache, or use a different test user.")
            return 1

    if args.only in {"all", "api"}:
        api_rows = benchmark_ai_api_calls(args.base_url.rstrip("/"), headers, args.repeats)
        api_ok = print_section("Function 3: AI API Calls (GET /api/ai/*)", api_rows)
        if not api_ok and all(r.status_code in {401, 403} for r in api_rows):
            print("Authentication/authorization failed for Function 3. Use a fresh valid customer access token.")
            return 1

    print("Done. Copy this output into your Session 1 evidence section.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
