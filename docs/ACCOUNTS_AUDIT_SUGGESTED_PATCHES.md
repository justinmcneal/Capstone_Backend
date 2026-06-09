Accounts — Suggested Line-Level Patches

This document lists low-risk, optional patches you can apply to improve readability, typing, and testability. None of these are required to make the system work; they are suggested cleanups.

1) Replace broad catches with `except Exception:` (if any remain)
- Files: search for `except:` occurrences. We already fixed `accounts/services/auth_service.py`.

2) Add missing exports to `accounts/views/__init__.py` (done)

3) Add `__repr__` helpers to models (optional, improves debugging)
- Example patch to apply to `accounts/models/customer.py`:

```diff
*** Update File: accounts/models/customer.py
@@ -1,6 +1,8 @@
     def to_dict(self):
         """Convert instance to dictionary for MongoDB operations"""
         return encrypt_fields(data, self.encrypted_fields)
+    
+    def __repr__(self):
+        return f"<Customer id={self.id} email={self.email}>"
```

4) Add light type hints to `accounts/utils/token_utils.py` public methods (optional)
- Example: annotate `generate_jwt_tokens(customer, token_type='no_remember_me') -> dict[str,str]`.

5) Tests: Add slow/critical smoke tests for auth flows
- Add pytest integration tests for:
  - Signup + OTP verification + login
  - Login + refresh token rotation + logout
  - 2FA flow (temp token -> confirm -> full tokens)

6) CI: Add a job to run `ruff check` and `black --check` in pre-commit or GitHub Actions (recommended)

7) Env safety: Ensure `SECRET_PEPPER` is present in staging/prod. Add a start-up check in `manage.py` that fails early if missing (optional).

If you want, I can apply any subset of these patches automatically. Tell me which ones to apply and I'll create commits on `fix/accounts-cleanups` and push them.
