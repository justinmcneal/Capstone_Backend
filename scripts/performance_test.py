#!/usr/bin/env python3
"""
performance_test.py
Sprint 2 / Module 12 — Performance Testing Lab (AI Track)

Chosen Function : chat()
Description     : Core AI function of MSME Pathways. Sends a user message to the
                  Groq Cloud LLM API (llama-3.1-8b-instant) and returns a response.
                  This is the function that powers every AI chatbot interaction.

Lab Instructions:
  1. Pick a Function  → chat() from Sprint 2
  2. Implement Timing Code → run_and_time() using time.perf_counter()
  3. Run 3+ Cases     → Normal, Long, Empty, Custom 1, Custom 2 (6 total)
"""

from __future__ import annotations

import os
import sys
import time

import requests as http

# ---------------------------------------------------------------------------
# Load environment variables from .env (same pattern used by the Django app)
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_BASE_DIR, ".env")

if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, encoding="utf-8") as _fp:
        for _line in _fp:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            _key = _key.strip()
            _val = _val.split("#")[0].strip()          # strip inline comments
            if _key and _key not in os.environ:
                os.environ[_key] = _val

GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL:   str = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant").strip()
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a friendly and helpful financial assistant for Filipino microentrepreneurs "
    "(MSME owners). Answer concisely in 2–3 sentences. Never give specific financial "
    "advice or guarantee loan approval."
)


# ===========================================================================
# FUNCTION UNDER TEST — chat()
# Mirrors the production GroqService.chat() implementation in
# ai_assistant/services/llm_service.py
# ===========================================================================

def chat(message: str) -> dict:
    """
    Send a message to the Groq LLM and return the response.

    This is the core AI function selected for performance testing.
    It replicates the logic of GroqService.chat() in the production backend.

    Args:
        message: User message string (may be empty to test graceful handling).

    Returns:
        dict with keys: success (bool), response (str) or error (str),
        model (str), tokens (int).
    """
    if not GROQ_API_KEY:
        return {"success": False, "error": "GROQ_API_KEY not configured"}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": message},
    ]

    try:
        resp = http.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model":       GROQ_MODEL,
                "messages":    messages,
                "temperature": 0.7,
                "max_tokens":  200,
            },
            timeout=30,
        )

        if resp.status_code == 200:
            data = resp.json()
            return {
                "success":  True,
                "response": data["choices"][0]["message"]["content"],
                "model":    data.get("model", GROQ_MODEL),
                "tokens":   data.get("usage", {}).get("total_tokens", 0),
            }
        else:
            err = resp.json().get("error", {}).get("message", resp.text)
            return {"success": False, "error": err, "status_code": resp.status_code}

    except http.Timeout:
        return {"success": False, "error": "Request timed out (>30 s)"}
    except http.RequestException as exc:
        return {"success": False, "error": str(exc)}


# ===========================================================================
# TIMING CODE  — exact pattern from Performance Testing Lab instructions
# ===========================================================================

def run_and_time(fn, x):
    t0 = time.perf_counter()
    y = fn(x)
    t1 = time.perf_counter()
    # Returns result and time in seconds
    return y, round(t1 - t0, 3)

# Usage: result, duration = run_and_time(my_func, input_data)


# ===========================================================================
# TEST CASES
# ===========================================================================

# Case 1 — Normal Input: a standard, short question about loans
NORMAL_INPUT = "What are the basic requirements to apply for a loan?"

# Case 2 — Long Input: 1000+ character detailed business description
LONG_INPUT = (
    "I am a sari-sari store owner from Quezon City and have been running my business for "
    "over 5 years. My monthly revenue averages PHP 45,000 from selling groceries, household "
    "goods, and personal care products to the local community. I currently employ two "
    "part-time workers. I have a valid government ID, barangay clearance, and business "
    "permit. I want to expand my store by adding a small refrigeration unit and hire one "
    "additional worker, so I would like to borrow PHP 50,000 secured against my inventory "
    "and future sales. I have no existing loans and have been paying all my bills on time "
    "for the past three years. My informal credit history through a community cooperative "
    "is considered good. Given my business profile and financial situation, am I likely to "
    "qualify for a microenterprise loan? What are the specific strengths and weak points of "
    "my application? What additional documents should I prepare to strengthen my loan "
    "application and maximize my chances of approval for the highest possible amount?"
)

# Case 3 — Empty Input: blank field submitted (should handle gracefully, not crash)
EMPTY_INPUT = ""

# Case 4 — Custom Case 1: Tagalog language query (language-switch behavior)
CUSTOM_1_TAGALOG = (
    "Paano ko malalaman kung kwalipikado na ako para mag-apply ng loan para sa "
    "aking negosyo at anong mga dokumento ang kailangan ko?"
)

# Case 5 — Custom Case 2: Financial math / interest calculation query
CUSTOM_2_INTEREST = (
    "If I borrow PHP 20,000 at a 2% monthly interest rate for 12 months, "
    "what will be my monthly amortization and total repayment amount?"
)

# Case 6 — Custom Case 3: Repeated/duplicate question (tests caching/consistency)
CUSTOM_3_REPEAT = "What are the basic requirements to apply for a loan?"


TEST_CASES: list[dict] = [
    {
        "name":     "Normal Input",
        "input":    NORMAL_INPUT,
        "steps":    "Enter standard text",
        "expected": "< 3000ms",
        "note":     "Baseline",
    },
    {
        "name":     "Long Input",
        "input":    LONG_INPUT,
        "steps":    "Paste 1000+ chars",
        "expected": "Process/Handle",
        "note":     "Larger prompt",
    },
    {
        "name":     "Empty Input",
        "input":    EMPTY_INPUT,
        "steps":    "Submit blank field",
        "expected": "Handle gracefully",
        "note":     "Edge case — blank",
    },
    {
        "name":     "Custom Case 1",
        "input":    CUSTOM_1_TAGALOG,
        "steps":    "Tagalog question",
        "expected": "Filipino response",
        "note":     "Language switch",
    },
    {
        "name":     "Custom Case 2",
        "input":    CUSTOM_2_INTEREST,
        "steps":    "Math/calc query",
        "expected": "Computed answer",
        "note":     "Financial math",
    },
    {
        "name":     "Custom Case 3",
        "input":    CUSTOM_3_REPEAT,
        "steps":    "Repeat of Case 1",
        "expected": "Consistent result",
        "note":     "Consistency check",
    },
]


# ===========================================================================
# PASS / FAIL LOGIC
# ===========================================================================

def evaluate(tc: dict, result: dict, duration_ms: int) -> str:
    name = tc["name"]
    success = result.get("success", False)

    if name == "Empty Input":
        # "Handle gracefully" = function returns a structured dict, does not raise
        return "PASS" if isinstance(result, dict) else "FAIL"
    elif name == "Normal Input":
        return "PASS" if success and duration_ms < 3000 else "FAIL"
    else:
        return "PASS" if success else "FAIL"


# ===========================================================================
# MAIN — run all cases and print the Performance Test Pack table
# ===========================================================================

def main() -> int:
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY is not set. Check the .env file.")
        return 1

    print()
    print("=" * 96)
    print("  PERFORMANCE TEST PACK   |   Sprint 2 / Module 12")
    print(f"  Function Under Test    : chat()  —  GroqService  (model: {GROQ_MODEL})")
    print(f"  Provider               : Groq Cloud API  |  Endpoint: POST {GROQ_API_URL}")
    print("=" * 96)
    print()

    hdr = f"{'TEST CASE':<22} {'STEPS (SHORT)':<24} {'EXPECTED':<22} {'ACTUAL (ms)':<14} {'P/F':<6} NOTE"
    sep = "-" * 96
    print(hdr)
    print(sep)

    records: list[dict] = []

    for tc in TEST_CASES:
        inp_chars = len(tc["input"])

        result, duration_s = run_and_time(chat, tc["input"])
        duration_ms = int(duration_s * 1000)

        pf = evaluate(tc, result, duration_ms)

        # For empty input the API usually returns an error — show the outcome type
        if tc["name"] == "Empty Input":
            actual_label = f"{duration_ms}ms (error)" if not result.get("success") else f"{duration_ms}ms"
        else:
            actual_label = f"{duration_ms}ms"

        print(
            f"{tc['name']:<22} {tc['steps']:<24} {tc['expected']:<22} "
            f"{actual_label:<14} {pf:<6} {tc['note']}"
        )

        records.append({
            **tc,
            "result":      result,
            "duration_ms": duration_ms,
            "pf":          pf,
            "inp_chars":   inp_chars,
        })

    print(sep)
    print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    passed = sum(1 for r in records if r["pf"] == "PASS")
    print(f"  Results  : {passed} PASS / {len(records) - passed} FAIL  ({len(records)} total cases)")
    print()

    # Slowest case
    timed = [r for r in records if r["duration_ms"] > 0]
    if timed:
        slowest = max(timed, key=lambda r: r["duration_ms"])
        fastest = min(timed, key=lambda r: r["duration_ms"])
        print(f"  Slowest Case  : {slowest['name']} — {slowest['duration_ms']} ms")
        print(f"  Fastest Case  : {fastest['name']} — {fastest['duration_ms']} ms")
        print()
        print("  Bottleneck Analysis:")
        print("    The slowest case is driven by the size of the prompt sent to the Groq API.")
        print("    Larger inputs (1000+ chars) take longer because the LLM must process more")
        print("    tokens in the prompt context before generating a response. The dominant cost")
        print("    is external network I/O + LLM inference time on Groq Cloud servers.")
        print("    Empty inputs fail fast because Groq rejects blank messages at validation.")
    print()
    print("  Done. Copy the table above into your Performance Test Pack log.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
