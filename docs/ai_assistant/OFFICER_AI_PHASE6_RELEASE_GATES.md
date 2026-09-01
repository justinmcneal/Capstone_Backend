# Officer AI Phase 6 release gates

The officer copilot is released only after the synthetic matrix, contract checks,
and application-level tests pass. The matrix is intentionally synthetic and
contains no customer prompts, identifiers, uploaded documents, or provider
responses.

## Matrix coverage

`tests/fixtures/officer_ai_phase6_evaluation_matrix.json` covers every backend
allowlist value for application lifecycle, document, installment, and schedule
states. It also includes complete, incomplete, unavailable, stale, and
contradictory evidence; online/offline provider behavior; English/Filipino
cases; privacy, prompt-injection, out-of-scope, and decision-request cases;
contract, browser, and officer-usability gates.

The usability case is passed only when the rendered brief gives an officer a
plain-language issue, a concrete next step, and an allowlisted navigation link.
Internal tool names, database fields, customer identifiers, and automated loan
decisions are never accepted as usable output.

## Local gates

Backend:

```text
.venv/bin/python -m pytest tests/test_ai_officer_phase6_evaluation.py tests/test_ai_stage6_quality_release.py -q
```

Portal:

```text
npm run check:officer-contract
npm run check:officer-release
npm run test:officer-contract
npm run test:officer-release
npm run type-check
npm run test -- --run
```

The real browser journey remains opt-in. Run it only against an approved
synthetic deployment with `RUN_AI_OFFICER_BROWSER_E2E=1` and the existing
officer E2E variables. It verifies the cookie/CSRF officer endpoint, one safe
terminal event, no canary leakage, and the officer-visible response.

## Release decision

The release is blocked on any contract mismatch, unavailable summary that is
not clearly reported, stale or contradictory evidence rendered as a confident
fact, PII/prompt-injection leakage, decision language, browser endpoint
failure, or a usability failure. Human officers remain responsible for review
and workflow decisions; this assistant does not approve or deny loans.
