# Notifications Production Readiness Review

Date: 2026-07-29  
Scope: Static code review of `notifications/` and related inbox, email, WebSocket, push-notification, and assignment-event behavior.

## Executive Summary

The `notifications/` module provides an in-app notification inbox, role-scoped access control, template-based email delivery, optional Celery async sends, real-time WebSocket broadcasts via Django Channels, FCM push notifications, and assignment-lifecycle event notifications. Core functionality is implemented and covered by multiple existing test files. Previously identified Celery mismatches have been fixed: `email_tasks.py` now calls the existing `EmailSender.send()` method, and `tests/test_notifications_use_celery.py` matches the current implementation. Notification testing and implementation documentation has been consolidated into a single canonical guide. This review documents any remaining gaps and recommended next steps.

## High Priority Findings

 1. `notifications/services/email_tasks.py` called a non-existent `EmailSender` method.  
    - `send_email_task()` previously invoked `sender._do_send(...)` at line 52, but `EmailSender` only exposes `send()`.  
    - Fixed: replaced with `sender.send(...)`. **Status: DONE.**

 2. `EmailSender` did not support the `use_celery` parameter expected by tests.  
    - `tests/test_notifications_use_celery.py` was rewritten to exercise the actual Celery task path using `send_email_task()` instead of constructing `EmailSender(use_celery=True)`.  
    - **Status: DONE.**

 3. `Notification` and `DeviceToken` indexes are bootstrapped in `init_db.py`.  
    - `init_db.py` imports both models and invokes `create_indexes()` on startup.  
    - Status: **DONE.**

## Medium Priority Findings

 1. No dedicated inbox API test file.  
    - Existing tests cover views in aggregate, mark-read, email sender, WebSocket, assignment events, isolation, and timestamps, but there is no `tests/test_notifications_api.py` focused on the 7 inbox endpoints with role enforcement, filters, pagination edge cases, and failure modes.  
    - Risk: regressions in list pagination, ownership scoping, delete semantics, and device-token registration won’t be caught automatically. **Status: GAP.**

 2. Documentation has been consolidated into a single canonical guide.  
    - `docs/NOTIFICATIONS_TESTING_GUIDE.md` now covers inbox API, WebSocket, FCM, assignment events, email templates, metrics, and smoke tests.  
    - `docs/NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` and `docs/NOTIFICATIONS_METRICS.md` have been merged and removed. **Status: DONE.**

 3. WebSocket consumer scope is narrow.  
    - `NotificationConsumer` handles `ping` and `mark_read` only.  
    - Risk: clients cannot mark-all-read, delete, or fetch unread count over WebSocket; they must fall back to REST. **Status: NEEDS REVIEW.**

## Low Priority Findings

No remaining low-priority findings.

## Current Strengths

1. Inbox API is role-qualified and ownership-scoped.  
   - `customer`, `loan_officer`, `admin`, and `super_admin` each have normalized owner queries.  
   - `super_admin` auth role is mapped to stored `admin` notification type.

2. Multi-channel delivery model is implemented.  
   - In-app records + WebSocket broadcast + optional email + optional FCM push.  
   - `channel` field distinguishes `email` vs `in_app`.

3. Notification lifecycle is tracked.  
   - `pending` -> `sent` / `failed` -> `read`.  
   - `sent_at` and `read_at` timestamps are recorded.

4. Celery task has autoretry with backoff.  
   - `send_email_task` retries on `Exception` with exponential backoff, `max_retries=3`.  
   - Prometheus counters track sync and async success/failure.

5. Assignment events are isolated into a dedicated service.  
   - `notifications/services/assignment_events.py` handles assign/reassign/unassign messaging with deduplicated recipients and structured metadata.

6. WebSocket auth middleware decodes JWT from query string or `sec-websocket-protocol` header.  
   - Supports both connection methods without requiring clients to share cookies.

## Implementation Gaps Since Last Review

- No notifications production-readiness review exists.
- `Notification` and `DeviceToken` indexes are not bootstrapped in `init_db.py`.
- `NOTIFICATIONS_TESTING_GUIDE.md` missing delete/register-token endpoints.
- Celery task expectations updated to match current `EmailSender` API.

## Production Readiness Checklist

 - [x] Inbox API with list, unread count, mark read, mark all read, delete, clear-all.
 - [x] Role-qualified ownership and ABAC scoping.
 - [x] Template-based email sender with 10+ notification helpers.
 - [x] Celery async email task with autoretry and backoff.
 - [x] Prometheus metrics for sync/async email sends.
 - [x] WebSocket real-time consumer with JWT auth and ping/pong.
 - [x] Assignment event notifications with deduplication.
 - [x] FCM push notification support with stale-token cleanup.
 - [x] Fix `email_tasks.py` to call existing `EmailSender.send()`.
 - [x] Update Celery tests to match actual `EmailSender` API.
 - [x] Add `Notification` and `DeviceToken` index bootstrap to `init_db.py`.
 - [x] Add dedicated inbox API tests (`tests/test_notifications_api.py`).
 - [ ] Consolidate duplicate notification docs into `NOTIFICATIONS_TESTING_GUIDE.md`.
 - [ ] Document `DELETE`, `clear-all`, and `register-token` endpoints in testing guide.

 ## Recommended Next Steps

 1. Consolidate `NOTIFICATIONS_TESTING_GUIDE.md` and `NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` into one canonical guide.
 2. Document `DELETE`, `clear-all`, and `register-token` endpoints in testing guide.

## Notes

- This review is code-level only (no live environment penetration testing).
- Notification endpoints mutate state and trigger side effects (email sends, WebSocket broadcasts, MongoDB writes, FCM pushes); tests should mock external I/O and assert on created records and broadcast calls.
