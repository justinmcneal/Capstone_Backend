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
| Tagalog chatbot quality improvements (advanced multilingual) | ⚠️ Basic TL support only | Add TL-focused prompt tuning, glossary/terminology control, and optional model routing for better EN/TL consistency | 🟡 Medium |

---

## Recommended Order

1. Implement `BlockchainService` integration.
2. Implement S3 storage backend and switch production storage to S3.
3. Deploy to Railway and run end-to-end verification.
4. Improve Tagalog chatbot quality with multilingual prompt/routing enhancements.
