# Accounts Package Audit Report

Date: 2026-05-28
Author: GitHub Copilot (automated review)

Summary
- Per-file scan of the `accounts/` package. Focus: syntax, duplicate imports, risky None handling, inconsistent patterns, and small cleanups.
- Applied three small fixes (see PR draft): token_utils, normalize_email, OTP comment.

High-level findings
- No syntax errors or import failures across scanned files.
- No duplicate imports found except the aliased `JWT_RefreshToken` which has been removed.
- `EmailUtils.normalize_email` previously returned `None` — this could flow into DB queries. It now returns an empty string.
- `accounts/utils/pepper_utils.py` raises when `SECRET_PEPPER` is missing (intended security behavior). Ensure environments set this.

Per-file notes & suggestions

- accounts/utils/token_utils.py
  - Fixed duplicated RefreshToken alias and unified parsing.
  - Suggestion: add type hints for public methods and document expected token claim keys.

- accounts/utils/email_utils.py
  - Now returns empty string for falsy input which avoids None queries.
  - Suggestion: consider raising on invalid email in strict flows; otherwise callers should treat empty string as "missing".

- accounts/services/otp_service.py
  - Cleaned a stale comment. OTP expiry is 10 minutes (config constant).

- accounts/models/*
  - Models use PyMongo-like patterns with `to_dict`/`from_dict`. Collections are sometimes singular (customer) and sometimes plural (loan_officers). This is likely intentional but document the convention.
  - Suggestion: add `__repr__` methods for easier REPL debugging.

- accounts/views/* and serializers
  - Validation flows are robust (many checks, sanitization). Several `try/except Exception` blocks log and return server errors — acceptable for now but consider scoping exceptions where possible.
  - Many views call `EmailUtils.normalize_email(str(request.data.get('email') or ''))`; with the normalize change this is safe.

- accounts/utils/pepper_utils.py
  - Security: raises ValueError when `SECRET_PEPPER` missing. Ensure CI/dev/staging have a generated pepper, or wrap usage in tests.

Lint & tests
- Ran `pytest` limited to `accounts` package — no tests were collected in this workspace for that path.
- Attempted to run linters (see CI/manual steps below). Recommend running `black` and `ruff` if available.

Next recommended actions
1. Run full test suite locally: `./venv/bin/python -m pytest -q`.
2. Run code formatters: `black accounts` and `ruff check accounts` (or equivalent) and fix any issues.
3. Review production/staging envs to ensure `SECRET_PEPPER` and JWT settings are configured.
4. (Optional) Add light type annotations to service/util public methods.

If you'd like, I can:
- open a PR on GitHub (branch created and pushed), or
- expand this report into per-line comments and suggested patches.
