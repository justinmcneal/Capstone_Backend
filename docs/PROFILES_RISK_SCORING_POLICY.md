# Profiles Risk-Scoring Policy

Last updated: 2026-08-09

## Status and Intended Use

Policy version: `2026-08-09-v1`

The Profiles risk score is an **informational profile-review signal**. It is not
an approval, rejection, pricing, credit-limit, adverse-action, or automated
lending decision. `risk_score_use` is returned and stored as
`informational_only`, and `risk_score_manual_review_required` is always true.

An officer or administrator must not use this score as the sole or controlling
basis for a lending decision. Product qualification, document verification,
affordability review, identity checks, consent, and authorized human review remain
separate controls.

Representative calibration and fairness validation are required before any
future proposal to use the score for approval, pricing, limits, prioritization, or
adverse decisions. Such a change requires a new policy version, documented
approval, client review, and recalculation of affected scores.

## Canonical Inputs

The API and scorer share the same canonical values.

- `household_income`: exact nonnegative monthly Philippine peso amount
- `loan_payment_history`: `on_time`, `sometimes_late`, `often_late`,
  `defaulted`, or `no_history`
- `utility_payment_history`: `on_time`, `sometimes_late`, or `often_late`
- `housing_status`: `owned`, `rented`, `living_with_family`, or
  `company_provided`
- `ewallet_usage`: `daily`, `weekly`, `monthly`, `rarely`, or `never`

Legacy stored income bands are accepted only to support controlled recalculation;
new API submissions use numeric income.

## Dimensions and Weights

| Dimension | Weight | Main signals |
| --- | ---: | --- |
| Financial stability | 25% | Numeric household-income band and existing-loan payment history |
| Payment behavior | 20% | Loan and utility payment histories |
| Social capital | 15% | Cooperative membership and declared community involvement |
| Housing stability | 25% | Housing status, time at address, and rent-to-income burden |
| Digital footprint | 15% | Bank/e-wallet availability, duration, and usage |

The weighted result is bounded to 0–100. A higher number maps to a lower
informational risk category:

- `low`: score at least 70
- `medium`: score from 40 through 69.99
- `high`: score below 40

Missing values use documented neutral or conservative defaults. Every
serializer-accepted enum has an explicit scoring rule; it does not silently fall
through a legacy `late` or unknown-value branch.

## Explanation Contract

Each completed score stores:

- policy version and intended use;
- input and calculated revisions;
- dimension names and scores;
- non-sensitive reason codes;
- overall score and category;
- calculation timestamp and status.

Reason codes describe categories such as `income_moderate`,
`loan_history_sometimes_late`, `housing_company_provided`, or
`digital_accounts_present`. They must not contain raw income, debt, addresses,
account identifiers, or other submitted profile values.

Customers can correct the underlying self-reported profile through the existing
profile update API. Every accepted update clears the previous published score and
requests a new revision. A future customer-facing dispute workflow may add more
formal review capability without changing this policy's informational boundary.

## Durability and Publication Rules

- Every alternative-data update atomically increments `risk_input_revision`.
- A task receives the exact revision it is allowed to calculate.
- Score publication uses a conditional `_id` plus revision update and changes
  only score-related fields.
- A task for an older revision is recorded as stale and cannot publish.
- Duplicate tasks for an already completed revision and policy are idempotent.
- Broker or scoring failures persist a machine-readable error type and failure
  timestamp without exposing exception messages to API clients.
- A one-minute reconciliation task requeues failed work and pending work that has
  exceeded the five-minute stale threshold.
- Successful, failed, and stale outcomes produce non-sensitive audit records.

## Change Management and Recalculation

Any change to inputs, mappings, weights, thresholds, categories, reason-code
meaning, or intended use requires:

1. A new immutable policy-version identifier.
2. Test updates for every canonical input and boundary.
3. Review of downstream customer, officer, loan, analytics, AI, and blockchain
   consumers.
4. Representative calibration and fairness review appropriate to the proposed
   use.
5. Approved client communication and manual-review guidance.
6. A dry-run inventory followed by controlled recalculation.

Inventory records that do not match the current policy without changing data:

```bash
python manage.py recalculate_profile_risk_scores
```

After staging validation and operational approval, queue the recalculation:

```bash
python manage.py recalculate_profile_risk_scores --apply
```

Use `--all` only when every record must be recalculated even if its stored policy
and revision are already current.

## Governance Limit

The implementation provides traceability and explanations; it does not itself
prove predictive validity, fairness, or legal suitability. Until representative
validation and formal approval exist, the score must remain informational and
must not be described to users or staff as an automated credit decision.
