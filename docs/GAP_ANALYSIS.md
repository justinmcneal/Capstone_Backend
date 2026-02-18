# MSME Pathways - Backend Gap Analysis (Pending Items Only)

> **Scope:** Backend only (frontend apps are complete)
> **Updated:** February 18, 2026

---

## Remaining Implementation Gaps

| Item | Current Status | What Is Missing | Priority |
|------|----------------|-----------------|----------|
| Smart Contracts / `BlockchainService` integration | ❌ Not implemented | Build Django ↔ Smart Contract bridge (`web3.py`), wire loan lifecycle + payment/audit writes on-chain, add retry/fallback and tx logging | 🔴 High |
| Production S3 document storage | ❌ Not implemented | Implement real `S3StorageBackend` (upload/delete/get_url), env-based backend switch, and migration path from local `media/` to S3 | 🔴 High |
| Production deployment (Railway) | ⚠️ Pending | Deploy backend service, set production env vars, run smoke tests for auth/docs/loans/analytics | 🔴 High |
| Multilingual AI (advanced) | ⚠️ Basic only | Add dedicated translation/tuning layer for stronger EN/TL consistency, terminology control, and response quality checks | 🟡 Medium |

---

## Clarifications

### AWS Deployment Option
- **Possible on AWS?** ✅ **Yes**
- **How hard to modify code for AWS deploy?** **Low to Medium**
- Current codebase can run on AWS with mostly infrastructure/config changes (compute/runtime, env vars, static/media handling), plus S3 backend implementation which is already needed for production-grade storage.

### Pre-Qualification Engine
- **Not a gap.** The pre-qualification engine is already implemented in backend logic and should remain excluded from pending-items-only tracking.

---

## Recommended Order

1. Implement `BlockchainService` integration.
2. Implement S3 storage backend and switch production storage to S3.
3. Deploy to Railway and run end-to-end verification.
4. Improve multilingual AI with a dedicated translation/tuning layer.
