# Profiles Client Migration Notes

Last updated: 2026-08-09

These notes describe the verified Profiles API contract that customer mobile,
loan-officer web, and admin web clients must use after Stages 2–7.

## Customer Mobile

- Send and display business age as `business_age_months`. The input-only
  `years_in_operation` alias temporarily converts exact whole-month values, but it
  is never returned. If both fields are sent, they must describe the same age.
- Send notification settings as JSON booleans (`true` or `false`). Strings,
  numbers, `null`, arrays, objects, and unknown preference keys return `400`.
- Use `profile_ready_for_application` for profile-only readiness. The
  `ready_for_loan` field is a deprecated compatibility alias and is not a product
  approval or document-readiness result.
- Use `profile_completion_policy_version` and `profile_missing_fields` to explain
  incomplete sections. Do not reproduce completion rules in the client.
- Preserve the latest `profile_revision`, send it with the next PUT, and reload
  after `409 Conflict` before reconciling the customer's edits.
- Treat alternative-data risk scoring as asynchronous. Refresh while
  `risk_score_status` is `pending`; show `failed` as retryable operational state;
  and describe completed scores as informational and manually reviewable.
- Monetary profile fields accept nonnegative values with at most two decimal
  places. Non-finite values and excess precision return field validation errors.
- Offer profile-only JSON download through `GET /api/profile/export/`; do not
  describe it as a complete account/document/loan export.
- Use `GET /api/profile/history/` for metadata-only change visibility.
- Allow a customer to request one manual review per completed score through
  `POST /api/profile/risk-reviews/` and show its status/resolution note.

## Loan-Officer Web

- Use `/api/officer/profiles/` and
  `/api/officer/profiles/<customer_id>/`. The
  `/api/profile/officer/<customer_id>/` route is a temporary compatibility alias.
- Treat an out-of-scope or hidden customer as `404`; do not infer whether that
  customer exists.
- Directory rows contain customer ID, name, and email only. Phone search/output,
  wallet data, account-security data, and emergency-contact data are not part of
  the officer contract.
- Display risk state, policy version, reason codes, and manual-review status.
  Never treat the profile risk score as an approval, price, credit limit,
  eligibility decision, or adverse-action reason.
- Use the scoped `/api/officer/profile-risk-reviews/` queue and send the latest
  `review_revision` when transitioning a request.

## Admin Web

The Profiles API intentionally grants no direct access to the `admin` role. No
admin frontend profile integration is required. A future administrative profile
feature must use a separate explicitly permissioned endpoint, an allowlisted
response, a documented purpose, and required sensitive-read auditing.

## Compatibility and Removal

| Compatibility surface | Current behavior | Client action |
| --- | --- | --- |
| `years_in_operation` | Input-only alias; exact conversion to months | Migrate to `business_age_months` |
| `ready_for_loan` | Deprecated alias of profile-only readiness | Migrate to `profile_ready_for_application` |
| `/api/profile/officer/<id>/` | Scoped legacy route alias | Migrate to `/api/officer/profiles/<id>/` |

Remove an alias only after deployed client telemetry or a coordinated release
confirms that no supported client still uses it. Alias removal is a separate
breaking API change and is not performed by Stage 6.
