# Profiles Completion and Application-Readiness Policy

Last updated: 2026-08-09

Policy version: `2026-08-09-v1`

## Meaning and Scope

`profile_completed` means one profile section contains every answer required by
this policy, including applicable conditional answers. `profiles_complete` and
`profile_ready_for_application` mean all three profile sections are complete.

These fields do not mean that:

- required documents exist or are approved;
- a customer satisfies a loan product's income, business-age, amount, term, or
  other eligibility rules;
- identity, consent, affordability, or fraud review has passed;
- the informational risk score approves the customer.

`ready_for_loan` remains temporarily available as a deprecated compatibility
alias for `profile_ready_for_application`. Clients must migrate to the new name.

## Required Personal Fields

- `date_of_birth`
- `gender`
- `civil_status`
- `nationality`
- `mobile_number`
- `address_line1`
- `barangay`
- `city_municipality`
- `province`
- `zip_code`

Emergency-contact fields, address line 2, and wallet address are optional for
completion. If an emergency phone is supplied, it must still be valid.

## Required Business Fields

- `business_name`
- `business_type`
- `business_address`
- `business_barangay`
- `business_city`
- `business_province`
- `business_age_months`
- `is_registered`
- `estimated_monthly_income`
- `income_range`
- `estimated_monthly_expenses`
- `number_of_employees`

If `business_type=other`, `business_type_other` is also required. If
`is_registered=true`, both `registration_type` and `registration_number` are
required. Selecting false clears obsolete registration details.

## Required Alternative-Data Fields

- `education_level`
- `employment_status`
- `years_of_experience`
- `housing_status`
- `years_at_current_address`
- `number_of_dependents`
- `household_income`
- `has_existing_loans`
- `has_bank_account`
- `has_ewallet`
- `pays_utilities`
- `is_coop_member`

Conditional requirements:

- Rented housing requires `monthly_rent`; other housing clears it.
- Existing loans require a positive `existing_loan_amount`, a non-`none`
  `existing_loan_source`, and a real `loan_payment_history`; selecting false
  clears all three.
- A bank account requires `bank_account_duration`; selecting false clears it.
- An e-wallet requires `ewallet_usage`; selecting false clears it.
- Paying utilities requires `utility_payment_history`; selecting false clears it.

False boolean answers and numeric zero answers are valid answered values; they
are not treated as missing.

## Completion Responses

Each section returns:

- `profile_completed`;
- `completion_percentage`;
- `profile_completion_policy_version`;
- `profile_missing_fields`, using codes such as `personal.mobile_number` or
  `alternative.bank_account_duration`;
- `profile_revision`, which is the edit-concurrency revision rather than the
  completion-policy version.

Summary `overall` returns the policy version, section count, averaged completion
percentage, `profile_ready_for_application`, the deprecated alias, and a combined
`missing_field_codes` list. Document status remains a separate summary object.

## Validation Contract

- Customer age must be from 18 through 100 on the request date.
- Stored BSON birth datetimes are returned as `YYYY-MM-DD`.
- Customer and emergency phones normalize to `+639XXXXXXXXX`.
- Philippine ZIP codes contain exactly four digits.
- Location names support Unicode letters, numbers after the first character,
  spaces, apostrophes, periods, and hyphens.
- Monetary inputs use two-decimal `Decimal` validation, reject non-finite or
  over-precision values, and use `Decimal128` when stored without encryption.

## Existing-Record Reconciliation

Inventory stored completion metadata without changing MongoDB:

```bash
python manage.py recalculate_profile_completion
```

After backup review and staging validation, persist the current derived fields:

```bash
python manage.py recalculate_profile_completion --apply
```

Writes are guarded by each record's `profile_revision`; concurrent changes are
reported as conflicts instead of being overwritten. Stage 5 did not run this
command against an actual development or production database.
