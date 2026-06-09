# Analytics Implementation and Testing Guide

## Scope
This guide covers analytics dashboards and audit log APIs under `/api/analytics/`.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/analytics`
- Required headers:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```
- All endpoints require authenticated JWT access.

## Role and Permission Rules
| Endpoint | Allowed Role | Required Admin Permission |
|---|---|---|
| `GET /admin/` | Admin | `view_analytics` |
| `GET /audit-logs/` | Admin | `view_logs` |
| `GET /audit-logs/users/` | Admin | `view_logs` |
| `GET /audit-logs/<log_id>/` | Admin | `view_logs` |
| `GET /officer/` | Loan Officer, Admin | None |
| `GET /officer/audit-logs/` | Loan Officer, Admin | None |
| `GET /customer/` | Customer | None |

## Endpoint Reference
1. `GET /admin/`
Returns system-wide metrics:
- `users`: `customers`, `loan_officers`, `admins`, `total`
- `loans`: `total`, `draft`, `pending`, `under_review`, `approved`, `rejected`, `disbursed`, `cancelled`
- `documents`: `total`, `pending`, `verified`
- `ai_usage`: `sessions_last_7_days`
- `products`: product-level application stats
- `recent_activity`: recent audit-log summaries

2. `GET /officer/`
Returns loan officer performance:
- `my_reviews`: `total_approved`, `total_rejected`, `approved_today`, `rejected_today`
- `queue`: `pending_total`, `assigned_to_me`
- `performance`: `total_reviewed`, `approval_rate`

3. `GET /customer/`
Returns customer-specific analytics:
- `applications`: `total`, `pending`, `approved`, `rejected`
- `documents`: `total`, `verified`, `pending`
- `profile_completion`: `percentage`, `personal_profile`, `business_profile`, `alternative_data`, `valid_id_uploaded`
- `ai_sessions`

4. `GET /audit-logs/`
Returns paginated, filterable audit logs.

Supported query params:
- `page` (default `1`, integer, minimum `1`)
- `page_size` (default `20`, integer, clamped to `1..200`)
- `action`
- `action_group` (`login`, `create`, `update`, `delete`)
- `user_id`
- `user_type`
- `date_from` (`YYYY-MM-DD`)
- `date_to` (`YYYY-MM-DD`)
- `search` (matches description, email, action, user ID, user type)

Response data keys:
- `logs`, `total`, `page`, `page_size`, `total_pages`

5. `GET /audit-logs/users/`
Returns unique users from audit logs for filter UIs.

Supported query params:
- `search`
- `limit` (default `200`, integer, clamped to `1..500`)

Response data keys:
- `users` (`user_id`, `user_type`, `user_email`, `label`)

6. `GET /audit-logs/<log_id>/`
Returns full detail for one audit log record.

## Smoke Test Sequence
1. Login as admin with `view_analytics` and `view_logs`.
2. Call `GET /admin/` and verify all top-level sections are present.
3. Call `GET /audit-logs/?page=1&page_size=20`.
4. Call `GET /audit-logs/users/?limit=50`.
5. Pick one log ID from step 3 and call `GET /audit-logs/<log_id>/`.
6. Login as loan officer and call `GET /officer/`.
7. Login as customer and call `GET /customer/`.
8. Negative test: customer/officer calls admin endpoint and receives `403`.

## Common Error Cases
1. `403 Forbidden`
- Missing role or missing admin permission (`view_analytics` or `view_logs`).

2. `400 Bad Request`
- Invalid query params: `page`, `page_size`, `limit`, or invalid `<log_id>`.

3. `404 Not Found`
- Audit log ID does not exist for `GET /audit-logs/<log_id>/`.
