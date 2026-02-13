## Reflection: Code Confidence Check (4 Persons, 2 Answers Each)

Based on `docs_ias/authentication_category1_readme.md` to `docs_ias/documentation_category5_readme.md`.

### 1) What security function are you most confident in, why?
- `Person 1`
  - `Answer A:` JWT validation + token blacklist; clear pass/fail test after logout.
  - `Answer B:` Account lockout; behavior is deterministic after repeated failed logins.
- `Person 2`
  - `Answer A:` Password hashing (`bcrypt`); hashes are non-plaintext and verifiable.
  - `Answer B:` 2FA flow; setup/confirm/verify endpoints are complete and testable.
- `Person 3`
  - `Answer A:` Role-based authorization; admin/officer/customer boundaries are enforced.
  - `Answer B:` Audit logging; security events are consistently captured.
- `Person 4`
  - `Answer A:` Document encryption at rest; encrypted storage and controlled decryption path exist.
  - `Answer B:` Security headers middleware; baseline response hardening is in place.

### 2) What part still feels uncertain or incomplete, why?
- `Person 1`
  - `Answer A:` Input validation consistency; some endpoints still use ad-hoc parsing.
  - `Answer B:` Query-param schema checks are not uniform.
- `Person 2`
  - `Answer A:` Threat modeling docs; no full STRIDE matrix yet.
  - `Answer B:` OWASP mapping is not explicitly documented.
- `Person 3`
  - `Answer A:` API docs sync; some routes are missing/misaligned in `docs/API_REFERENCE.md`.
  - `Answer B:` Central troubleshooting is scattered across multiple docs.
- `Person 4`
  - `Answer A:` DB security ops; encrypted backups are not implemented in repo code.
  - `Answer B:` TLS/at-rest DB encryption are infrastructure-dependent, not strictly enforced by app code.

### 3) What tool/framework/method helped improve design, why?
- `Person 1`
  - `Answer A:` DRF serializers; standardized input validation and cleaner errors.
  - `Answer B:` Manual negative testing via `curl`; quickly exposed weak paths.
- `Person 2`
  - `Answer A:` Checklist-based category review; made gaps measurable.
  - `Answer B:` `rg` repo-wide search; fast evidence gathering and traceability.
- `Person 3`
  - `Answer A:` Security demo harness (`scripts/security_demo_cli.py`); end-to-end validation.
  - `Answer B:` Dedicated testing guides in `docs/`; improved reproducibility.
- `Person 4`
  - `Answer A:` Code references per finding; reduced ambiguity in reporting.
  - `Answer B:` Route-vs-doc comparison script; caught documentation drift.

### 4) What feedback from the last session did you act on, why?
- `Person 1`
  - `Answer A:` Clarified what `Partial` means per control.
  - `Answer B:` Added exact tests and expected outputs.
- `Person 2`
  - `Answer A:` Added correctness criteria, not just status labels.
  - `Answer B:` Linked findings directly to file evidence.
- `Person 3`
  - `Answer A:` Improved practical test steps for each category.
  - `Answer B:` Distinguished implemented controls vs. policy-level gaps.
- `Person 4`
  - `Answer A:` Added overall verdict + prioritized next steps.
  - `Answer B:` Kept explanations short and audit-friendly.

---

## Reflection: Think Back and Think About (4 Persons, 2 Answers Each)

### Think Back: Which vulnerability turned out more serious than expected? What helped discover/fix it?
- `Person 1`
  - `Answer A:` Inconsistent server-side validation was more serious than expected because one weak endpoint can bypass protections even if most endpoints are secure.
  - `Answer B:` We discovered it through malformed-input testing plus endpoint-by-endpoint review, then prioritized serializer-based validation for write and query parameters.
- `Person 2`
  - `Answer A:` Documentation drift was riskier than expected because testers and developers could trust outdated endpoints and miss real exposure points.
  - `Answer B:` We confirmed it by comparing actual URL files against `docs/API_REFERENCE.md`, then listed missing routes as concrete update items.
- `Person 3`
  - `Answer A:` Partial NoSQL/XSS coverage outside sanitized serializers became more serious than expected since protection looked strong in auth flows but weaker in other modules.
  - `Answer B:` We found it by tracing sanitizer usage across serializers/views and testing unsanitized paths with payload variations.
- `Person 4`
  - `Answer A:` Missing a formal threat model created blind spots because controls existed, but there was no full mapping from components/data flows to threats and mitigations.
  - `Answer B:` This became clear during STRIDE/OWASP artifact searches and checklist-based gap review, which showed missing traceability.

### Think About: How did feedback change secure coding understanding? How will this guide future work?
- `Person 1`
  - `Answer A:` Feedback changed my view from “secure features exist” to “secure behavior must be consistent across all endpoints and roles.”
  - `Answer B:` Future work: enforce serializer/schema validation everywhere, especially for query params and manual request parsing paths.
- `Person 2`
  - `Answer A:` I now treat security quality as something that must be testable and repeatable, not something assumed from implementation intent.
  - `Answer B:` Future work: attach negative tests to each feature change and keep expected-failure behavior documented.
- `Person 3`
  - `Answer A:` Feedback showed that clear traceability increases confidence and speeds reviews because findings are linked to exact code and docs.
  - `Answer B:` Future work: maintain threat-to-control-to-test mapping so each mitigation has a direct verification path.
- `Person 4`
  - `Answer A:` I now view documentation accuracy as part of security posture, since stale docs can cause wrong assumptions during operations and testing.
  - `Answer B:` Future work: update docs, tests, and verification checks in the same PR as code to reduce drift.
