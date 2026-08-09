# Profiles Operations and Monitoring

Last updated: 2026-08-09

## Runtime Workflows

- `profiles.reconcile_risk_scores` runs every minute and recovers failed or
  abandoned score calculations.
- `profiles.reconcile_audit_failures` runs every minute and replays allowlisted queued
  Profiles audit payloads. Resolved queue entries have their replay payload
  removed.
- `profiles.collect_operational_metrics` runs every 15 minutes. It performs
  read-only inventories of profile duplicates, declared encryption coverage,
  unresolved audit writes, and open risk reviews.

The operational metrics task does not repair data. Reconciliation, encryption,
and index commands remain dry-run/review workflows requiring explicit approval
before `--apply` or production execution.

## Development Inventory Baseline

The approved read-only development inventory on 2026-08-09 reported zero profile
duplicates, obsolete completion records, obsolete risk scores, retained deleted-
customer profile records, and legacy business-age candidates. The Profiles
collections reported no encryption failures and contained no documents.

The shared cross-domain encryption scan initially found one plaintext customer
field and four decryptable legacy ciphertext fields. The approved remediation
cleared two expired OTP states and one disabled customer 2FA setup, then migrated
the customer phone and active admin 2FA secret. Verification completed with zero
failures, unsupported values, or conflicts. Deployment-target inventories must
still be reviewed independently.

## Prometheus Metrics

| Metric | Meaning |
| --- | --- |
| `profiles_audit_write_failures_total{action}` | Audit writes that failed initially |
| `profiles_operations_total{operation,outcome}` | Export, history, review, reconciliation, and denied-access outcomes |
| `profiles_risk_score_events_total{outcome}` | Complete, failed, stale, and enqueue-failed scoring events |
| `profiles_risk_score_backlog{status}` | Failed or abandoned-pending score work |
| `profiles_duplicate_records{collection}` | Extra records sharing a canonical customer ID |
| `profiles_unprotected_sensitive_fields{collection}` | Populated declared fields not using the encrypted envelope |
| `profiles_audit_failure_backlog` | Audit writes still awaiting replay |
| `profiles_risk_review_backlog{status}` | Pending and in-review customer requests |

Suggested alert starting points must be tuned to real traffic and an approved
on-call policy:

```promql
increase(profiles_audit_write_failures_total[10m]) > 0
profiles_audit_failure_backlog > 0
profiles_duplicate_records > 0
profiles_unprotected_sensitive_fields > 0
profiles_risk_score_backlog{status="failed"} > 0
profiles_risk_score_backlog{status="stale_pending"} > 0
increase(profiles_operations_total{operation="unauthorized_profile_access",outcome="denied"}[15m]) > 10
profiles_risk_review_backlog{status="pending"} > 20
```

## Customer Export and History

`GET /api/profile/export/` generates an allowlisted JSON representation in
memory. It does not create a server-side export file. A required audit must be
stored or queued before data is returned; if the primary audit write fails, the
request fails closed with `503`.
The export includes at most 100 risk-review records and reports the full count and
truncation state to keep one response bounded.

`GET /api/profile/history/` returns change metadata such as section, revision,
changed field names, and timestamps. It intentionally omits previous/current
field values, IP addresses, and account-security information. The audit failure
reconciler makes best-effort mutation history recoverable, but this view is not a
cryptographic or statutory record of historical field values.

## Risk Review Workflow

Customers may create one request per completed scoring revision through
`/api/profile/risk-reviews/`. Loan officers can list only requests for customers
inside their existing application/document scope and transition them through
`in_review` to `resolved` or `rejected`. Terminal transitions require a resolution
note and use `review_revision` optimistic concurrency.
Customer descriptions and officer resolution notes are declared encrypted fields
and participate in the shared encryption backfill/rotation/verification command.

The workflow does not make the informational score authoritative. A review is a
human correction/explanation channel, not an automated approval or adverse-action
process.

## Deletion Lifecycle

Final account deletion removes personal, business, alternative-data, and risk-review
records through the idempotent Profiles cleanup service. It also removes unresolved
Profiles audit-recovery payloads associated with that customer, including queued
officer actions. Successfully reconciled queue entries contain no replay payload.

## Deliberate Deferrals

- Profile avatars remain unimplemented. No validated product requirement offsets
  the additional uploaded-media validation, moderation, storage, retention, and
  privacy surface.
- A Philippine address reference dataset remains unbundled. Introducing one
  requires a maintained authoritative source, update/version policy, stable
  identifiers, and client migration plan. Current Unicode/numbered-location and
  ZIP validation remains the supported contract.
