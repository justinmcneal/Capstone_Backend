#!/usr/bin/env python3
"""
Run short, rule-based accuracy checks against the AI assistant API.

This script loads test cases from docs/AI_ASSISTANT_ACCURACY_SHORT_TESTS.json,
calls /api/ai/chat/ for each prompt, and evaluates responses using simple
regex-based rules (pass/fail).
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Tuple

import requests


DEFAULT_TESTS_PATH = "docs/AI_ASSISTANT_ACCURACY_SHORT_TESTS.json"


def _load_tests(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _match_any(patterns: List[str], text: str) -> bool:
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE | re.DOTALL):
            return True
    return False


def _match_all(patterns: List[str], text: str) -> bool:
    for p in patterns:
        if not re.search(p, text, flags=re.IGNORECASE | re.DOTALL):
            return False
    return True


def _count_matches(patterns: List[str], text: str) -> int:
    count = 0
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE | re.DOTALL):
            count += 1
    return count


def _evaluate_requirements(require: List[Dict[str, Any]], text: str) -> List[str]:
    failures = []
    for req in require:
        label = req.get("label", "requirement failed")
        if "any_of" in req:
            if not _match_any(req["any_of"], text):
                failures.append(label)
        elif "all_of" in req:
            if not _match_all(req["all_of"], text):
                failures.append(label)
        elif "min_any" in req:
            min_any = req["min_any"]
            count = _count_matches(min_any.get("patterns", []), text)
            if count < int(min_any.get("count", 0)):
                failures.append(label)
        else:
            failures.append(f"{label} (unknown rule)")
    return failures


def _evaluate_forbidden(forbid: List[Dict[str, Any]], text: str) -> List[str]:
    hits = []
    for rule in forbid:
        label = rule.get("label", "forbidden rule triggered")
        if "any_of" in rule and _match_any(rule["any_of"], text):
            hits.append(label)
    return hits


def _extract_response(payload: Dict[str, Any]) -> str:
    data = payload.get("data", {})
    # Normal chat response uses 'response'; filtered responses use 'message'
    return data.get("response") or data.get("message") or ""


def _call_chat(base_url: str, token: str, prompt: str, language: str) -> Tuple[str, Dict[str, Any], str]:
    url = base_url.rstrip("/") + "/api/ai/chat/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    conversation_id = str(uuid.uuid4())
    payload = {
        "message": prompt,
        "language": language,
        "conversation_id": conversation_id,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        return "", {}, f"request error: {e}"

    try:
        body = resp.json()
    except ValueError:
        return "", {}, f"invalid JSON response (status {resp.status_code})"

    if resp.status_code >= 400 or body.get("status") != "success":
        return "", body, f"API error (status {resp.status_code})"

    return _extract_response(body), body, ""


def _filter_tests(all_tests: List[Dict[str, Any]], ids: str) -> List[Dict[str, Any]]:
    if not ids:
        return all_tests
    allow = {i.strip().upper() for i in ids.split(",") if i.strip()}
    return [t for t in all_tests if t.get("id", "").upper() in allow]


def run():
    parser = argparse.ArgumentParser(description="AI assistant short accuracy evaluation")
    parser.add_argument("--base-url", default=os.getenv("AI_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("AI_TOKEN", ""))
    parser.add_argument("--tests", default=DEFAULT_TESTS_PATH)
    parser.add_argument("--ids", default="", help="Comma-separated test IDs to run (e.g., T01,T02)")
    parser.add_argument("--delay-ms", type=int, default=200, help="Delay between requests in ms")
    parser.add_argument("--dry-run", action="store_true", help="List tests without calling the API")
    parser.add_argument("--print-responses", action="store_true", help="Print model responses")
    parser.add_argument("--out", default="", help="Write JSON results to a file")
    args = parser.parse_args()

    tests_payload = _load_tests(args.tests)
    tests = _filter_tests(tests_payload.get("tests", []), args.ids)

    if args.dry_run:
        print(f"Loaded {len(tests)} test(s) from {args.tests}")
        for t in tests:
            print(f"- {t.get('id')}: {t.get('name')} [{t.get('language')}]")
        return 0

    if not args.token:
        print("Missing token. Set AI_TOKEN or pass --token.", file=sys.stderr)
        return 2

    results = []
    passed = 0
    failed = 0

    for idx, test in enumerate(tests, start=1):
        prompt = test.get("prompt", "")
        language = test.get("language", "en")

        response_text, raw_body, error = _call_chat(args.base_url, args.token, prompt, language)
        if error:
            result = {
                "id": test.get("id"),
                "name": test.get("name"),
                "prompt": prompt,
                "language": language,
                "pass": False,
                "error": error,
                "response": response_text,
            }
            failed += 1
            results.append(result)
            print(f"[{test.get('id')}] FAIL - {error}")
        else:
            require_failures = _evaluate_requirements(test.get("require", []), response_text)
            forbid_hits = _evaluate_forbidden(test.get("forbid", []), response_text)
            ok = not require_failures and not forbid_hits

            result = {
                "id": test.get("id"),
                "name": test.get("name"),
                "prompt": prompt,
                "language": language,
                "pass": ok,
                "require_failures": require_failures,
                "forbid_hits": forbid_hits,
                "response": response_text,
                "raw": raw_body,
            }
            results.append(result)
            if ok:
                passed += 1
                print(f"[{test.get('id')}] PASS")
            else:
                failed += 1
                details = []
                if require_failures:
                    details.append("missing: " + "; ".join(require_failures))
                if forbid_hits:
                    details.append("forbidden: " + "; ".join(forbid_hits))
                print(f"[{test.get('id')}] FAIL - " + " | ".join(details))

            if args.print_responses:
                print("Response:")
                print(response_text.strip() or "<empty>")

        if idx < len(tests):
            time.sleep(max(args.delay_ms, 0) / 1000.0)

    total = passed + failed
    accuracy = (passed / total * 100) if total else 0.0
    print(f"\nSummary: {passed}/{total} passed ({accuracy:.1f}%)")

    output = {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "accuracy_percent": round(accuracy, 2),
        },
        "results": results,
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Saved results to {args.out}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
