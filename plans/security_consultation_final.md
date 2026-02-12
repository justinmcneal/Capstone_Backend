# Session 2: Consultation Round Checklist
## MSME Pathways Backend - Security Verification
## (Aligned with `docs_ias/*_category*_readme.md`)

## SLIDE 1: Category 1 - Authentication

**Current Status:** `Partially Implemented`

**Implemented:**
- bcrypt password hashing for customer/admin/loan-officer models
- JWT auth with token expiry and token blacklisting on logout
- Generic customer login error handling (no email-enumeration details)
- 2FA capability is available (setup/confirm/verify flows)
- Rate-limit controls for customer login: IP throttle + 30-second per-user window
- Account lockout controls are present

**Improvement Needed:**
- Login throttling is partial across roles (admin/loan officer rely on lockout only)
- MFA is available but not enforced by policy
- Password-policy handling is not fully uniform across all role-specific flows

**Plan to Fix:**
1. Decide policy for privileged-role login throttling (keep lockout-only or add DRF throttles with role-aware limits).
2. Enforce MFA for admin/loan officer accounts (or document risk acceptance).
3. Standardize password-validation handling across all auth flows.

---

## SLIDE 2: Category 2 - Input Validation

**Current Status:** `Partially Implemented`

**Implemented:**
- Serializer-based validation exists across many critical endpoints
- Input sanitizer exists for XSS/NoSQL pattern blocking in selected serializers
- File upload validation (type + size) is implemented for document upload
- CSRF middleware is enabled in Django settings
- SQL injection is N/A in architecture (MongoDB backend, no SQL execution layer)

**Improvement Needed:**
- Validation is not uniform across all endpoints (ad-hoc request parsing still exists)
- API schema enforcement is partial
- XSS/NoSQL protections are not consistently applied across all apps/fields
- CSRF is not a strong active control for bearer-token API paths

**Plan to Fix:**
1. Require serializers for all write endpoints and query-parameter schemas.
2. Replace ad-hoc parsing with shared typed validators for pagination/filter/search.
3. Expand sanitizer/strict validators to uncovered inputs.
4. Document explicit CSRF strategy for JWT/bearer usage.

---

## SLIDE 3: Category 3 - Database Security

**Current Status:** `Partially Implemented`

**Implemented:**
- Environment-based credential loading is in place
- Application-level RBAC is broadly enforced
- Document storage encryption at rest is implemented (AES-256-GCM)
- Audit logging is enabled across key security/business flows
- Several unique/TTL index hardening controls are defined

**Improvement Needed:**
- No encrypted DB backup implementation in backend code
- MongoDB at-rest encryption and TLS are URI/infrastructure-dependent, not app-enforced
- No vault/KMS integration for secrets in repo
- Index bootstrap automation is incomplete across all models

**Plan to Fix:**
1. Add/confirm encrypted backup policy and document evidence.
2. Enforce DB connection security checks at startup (URI scheme/TLS requirements).
3. Expand index bootstrap/init coverage to all model index definitions.
4. Harden secret handling for production (fail fast on missing required secrets).

---

## SLIDE 4: Category 4 - Threat Modeling

**Current Status:** `Partially Implemented`

**Implemented:**
- High-level flow/architecture artifacts exist in docs
- Security controls are implemented and documented at control level
- Mitigations and priorities exist in general planning docs

**Improvement Needed:**
- No formal STRIDE threat model artifact
- No explicit OWASP Top 10 mapping matrix
- No security risk matrix with likelihood/impact scoring
- No formal threat-model maintenance cadence

**Plan to Fix:**
1. Create `docs_ias/threat_model_master.md`.
2. Add STRIDE entries per component/data flow with ownership/status.
3. Add OWASP mapping columns (`A01`-`A10`) and risk scoring.
4. Add update cadence (per release/monthly) and changelog policy.

---

## SLIDE 5: Category 5 - Documentation

**Current Status:** `Partially Implemented`

**Implemented:**
- Security docs, deployment docs, API reference, and module guides exist
- Documentation is mostly organized under `docs/`
- Domain-specific troubleshooting notes exist

**Improvement Needed:**
- README completeness/freshness drift
- API reference not fully synchronized with current routes
- Troubleshooting and maintenance notes are not centralized
- No central docs index (`docs/README.md`)

**Plan to Fix:**
1. Update README totals/sections and add troubleshooting + maintenance coverage.
2. Sync `docs/API_REFERENCE.md` with all live routes.
3. Add `docs/README.md` index and `docs/OPERATIONS_RUNBOOK.md`.
4. Define maintenance cadence/owners/checklists for operational docs.

---

## SLIDE 6: Overall Security Summary

### Overall Security Assessment

| Area | Status | Implemented Highlights | Main Gaps | Plan to Fix |
|------|--------|------------------------|-----------|-------------|
| **Authentication** | Partial | bcrypt, JWT+blacklist, 2FA available, lockout + customer login throttles | Privileged-role throttling policy, MFA enforcement policy, flow consistency | Define/enforce role-based auth hardening policy |
| **Input Validation** | Partial | Serializer validation in many endpoints, sanitizer in selected paths, file validation | Inconsistent validation coverage and schema enforcement | Standardize serializers and query validation across all endpoints |
| **Database Security** | Partial | Env-based secrets, app RBAC, audit logs, document encryption, index controls | Backups, TLS/at-rest enforcement, vault/KMS, full index automation | Add backup/TLS/index hardening controls and documentation |
| **Threat Modeling** | Partial | High-level flows and security control docs | No formal STRIDE/OWASP/risk matrix/cadence | Create formal threat-model artifact and governance process |
| **Documentation** | Partial | Broad docs coverage exists | Drift, no central troubleshooting/runbook/index | Synchronize docs and add operations-focused documentation |

**Final Verdict:** `Partially Implemented` (not yet full checklist compliance)

---

## Evidence Reference (Source of Truth)

- `docs_ias/authentication_category1_readme.md`
- `docs_ias/input_validation_category2_readme.md`
- `docs_ias/database_security_category3_readme.md`
- `docs_ias/threat_modeling_category4_readme.md`
- `docs_ias/documentation_category5_readme.md`

---

**Format:** Project Area -> Implemented -> Improvement Needed -> Plan to Fix  
**Recommendation:** Present as "progress with prioritized hardening roadmap", not "100% complete".
