Title: Small cleanups in `accounts` (token handling, email normalization, comments)

Summary
- Removed a duplicate/aliased import of `RefreshToken` in `accounts/utils/token_utils.py` and unified usage.
- Made `EmailUtils.normalize_email()` return an empty string for falsy input to avoid passing `None` into DB queries.
- Tidy: removed an outdated parenthetical remark in `accounts/services/otp_service.py`.

Why
- These changes are small, reduce confusion, and prevent subtle runtime None usages in queries.

Files changed
- accounts/utils/token_utils.py
- accounts/utils/email_utils.py
- accounts/services/otp_service.py

Checklist for reviewers
- [ ] Sanity-check token rotation flows and refresh token parsing
- [ ] Verify normalize_email change aligns with callers (most already pass str(... or ''))
- [ ] Run tests locally and validate auth flows (login/refresh/logout/2FA)

Suggested commands to verify locally
```bash
./venv/bin/python -m pytest -q accounts
./venv/bin/python -m pytest -q tests  # run full tests if available
```

Notes
- No behavioral changes expected beyond safer handling of falsy emails.
