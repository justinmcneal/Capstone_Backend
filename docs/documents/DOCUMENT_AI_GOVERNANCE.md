# Document AI Governance

Last updated: 2026-08-11

## Production Decision

Document CNN and image-quality inference are disabled for the approved
production baseline. Deploy with `DOCUMENT_UPLOAD_AI_ANALYSIS=False`. The
system continues structural validation, resource limits, PDF policy, fail-closed
malware scanning, and authorized human review; it must not use quality-only
analysis as a production fallback when a CNN artifact is absent.

The remaining sections govern development and any future proposal to enable
document AI. Dataset remediation, independent evaluation, artifact approval,
threshold calibration, and drift monitoring are mandatory before that optional
feature can be enabled, but are not blockers for the non-CNN Documents module.
Disabling the feature does not authorize use or distribution of the inventoried
dataset; it must be excluded from production artifacts and handled under a
separate approved privacy and repository-history process.

## Intended Use and Prohibited Use

Document AI is an advisory triage tool for image quality and claimed document-
type consistency. It may prioritize manual review or mark an unreviewed upload
as `needs_review`. It must never approve or reject a document, determine loan
eligibility, infer identity, or override a loan officer/admin decision.

Every result carries `manual_review_required: true`. Customers must have a
document reviewed by an authorized person and may correct or replace it through
the existing re-upload workflow. A customer-facing rejection must contain the
human review reason, not an opaque model score.

## Consent and Privacy

- The worker re-checks current AI consent immediately before reading bytes.
- Missing, withdrawn, expired, or unreadable consent fails closed as
  `skipped_no_consent`; no inference occurs.
- Training/evaluation samples require recorded source, license or consent basis,
  anonymization approval, immutable SHA-256, subject grouping, and split.
- Approved datasets belong in access-controlled versioned storage, not ordinary
  Git. Existing repository history requires a separately approved governance
  review; ordinary remediation must not rewrite history.

## Artifact Approval and Rollback

Inference loads an artifact only when its registry entry says `approved` and
its SHA-256 matches. The registry must also identify the model, code,
preprocessing, dataset manifest, threshold policy, evaluation metrics,
deployment date, and rollback target. Training creates a `not_approved` entry;
it cannot self-approve its output.

`DOCUMENT_AI_REQUIRE_APPROVED_MODEL=True` makes `/api/health/` degraded when an
approved artifact cannot load. Disable analysis or roll back to the recorded
approved artifact if integrity, latency, drift, or safety gates fail.

## Optional CNN Enablement Gates

Before approval, an independent immutable holdout evaluation must publish:

- sample counts and 95% confidence intervals overall and per class;
- macro/per-class precision, recall, and F1 plus confusion matrix;
- calibration error and reliability plots;
- false-accept and false-reject rates at the proposed per-class thresholds;
- device, lighting, capture-quality, and approved subgroup robustness;
- unknown/out-of-distribution rejection performance; and
- latency and memory at the production worker limits.

No class may be approved with fewer than the governance-approved independent
subject count. The current repository metrics and data inventory do not satisfy
these gates. `other` must not be forced into a known class; production approval
requires an explicit unknown/OOD outcome and a documented policy for `other`.

## Monitoring and Change Control

Monitor pending/retry/failed/stale analysis counts, latency, model-unavailable
events, score/confidence distribution, per-class review disagreement, appeals,
and consent skips. Alert thresholds and drift windows must be selected during
Stage 7 deployment validation. Any model, preprocessing, class mapping,
threshold, or dataset change creates a new registry version and repeats the
approval gates. The final holdout set is never used for tuning.
