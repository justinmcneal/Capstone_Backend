# Notifications Production Readiness Review

Date: 2026-07-29  
Scope: Static code review of `notifications/` and related inbox, email, WebSocket, push-notification, and assignment-event behavior.

## Executive Summary

The `notifications/` module provides an in-app notification inbox, role-scoped access control, template-based email delivery, optional Celery async sends, real-time WebSocket broadcasts via Django Channels, FCM push notifications, and assignment-lifecycle event notifications. Core functionality is implemented and covered by multiple existing test files. Two Celery-related tests are currently failing due to an API mismatch between `email_sender.py` and `email_tasks.py`. A production-readiness review and consolidated testing guide do not yet exist for this module.

## High Priority Findings

1. `notifications/services/email_tasks.py` calls a non-existent `EmailSender` method.  
   - `send_email_task()` invokes `sender._do_send(...)` at line 52, but `EmailSender` only exposes `send()`.  
   - Risk: Celery email task crashes at runtime. **Status: BUG.**

2. `EmailSender` does not support the `use_celery` parameter expected by tests.  
   - `tests/test_notifications_use_celery.py` constructs `EmailSender(use_celery=True)`, but `EmailSender.__init__()` accepts no arguments.  
   - Risk: test suite is out of sync with implementation. **Status: BUG.**

3. Missing `init_db.py` bootstrap for notification collections.  
   - `notifications/models/notification.py` defines `Notification.create_indexes()` and `notifications/models/device_token.py` defines `DeviceToken.create_indexes()`, but `init_db.py` does not import or invoke them.  
   - Risk: audit/inbox queries on `user_id`, `created_at`, `status`, and `token` will be unindexed as data grows. **Status: GAP.**

## Medium Priority Findings

1. No dedicated inbox API test file.  
   - Existing tests cover views in aggregate, mark-read, email sender, WebSocket, assignment events, isolation, and timestamps, but there is no `tests/test_notifications_api.py` focused on the 7 inbox endpoints with role enforcement, filters, pagination edge cases, and failure modes.  
   - Risk: regressions in list pagination, ownership scoping, delete semantics, and device-token registration won’t be caught automatically. **Status: GAP.**

2. Documentation is split across two guides.  
   - `docs/NOTIFICATIONS_TESTING_GUIDE.md` (413 lines) and `docs/NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` (96 lines) cover the same inbox endpoints.  
   - Risk: one doc may fall out of sync with the code. **Status: NEEDS CONSOLIDATION.**

3. WebSocket consumer scope is narrow.  
   - `NotificationConsumer` handles `ping` and `mark_read` only.  
   - Risk: clients cannot mark-all-read, delete, or fetch unread count over WebSocket; they must fall back to REST. **Status: NEEDS REVIEW.**

4. Direct thread dispatch is still used in documents reviewer notification path.  
   - `notify_reviewers_document_pending_async()` starts a daemon thread directly from a request path in `documents/views/document_views.py`.  
   - Risk: lifecycle control and observability are weaker than task-queue-based dispatch. **Status: NEEDS REVIEW.**

## Low Priority Findings

1. Missing endpoint documentation in testing guide.  
   - `DELETE /clear-all/`, `DELETE /<id>/`, and `POST /register-token/` are not documented in `docs/NOTIFICATIONS_TESTING_GUIDE.md`.  
   - Risk: API consumers miss inbox mutation operations. **Status: NEEDS FIX.**

2. `EmailSender.send()` catches exception and returns `False`, but `email_tasks.py` expects `_do_send()` to raise so Celery autoretry can trigger.  
   - If `_do_send` were added as a bare wrapper, it would need to re-raise exceptions to preserve retry behavior. **Status: NEEDS REVIEW.**

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
- Celery task crashes due to `_do_send` mismatch.
- `Notification` and `DeviceToken` indexes are not bootstrapped in `init_db.py`.
- `NOTIFICATIONS_TESTING_GUIDE.md` missing delete/register-token endpoints.

## Production Readiness Checklist

- [x] Inbox API with list, unread count, mark read, mark all read, delete, clear-all.
- [x] Role-qualified ownership and ABAC scoping.
- [x] Template-based email sender with 10+ notification helpers.
- [x] Celery async email task with autoretry and backoff.
- [x] Prometheus metrics for sync/async email sends.
- [x] WebSocket real-time consumer with JWT auth and ping/pong.
- [x] Assignment event notifications with deduplication.
- [x] FCM push notification support with stale-token cleanup.
- [ ] Fix `email_tasks.py` to call existing `EmailSender.send()`.
- [ ] Add `Notification` and `DeviceToken` index bootstrap to `init_db.py`.
- [ ] Add dedicated inbox API tests (`tests/test_notifications_api.py`).
- [ ] Create `docs/NOTIFICATIONS_PRODUCTION_READINESS_REVIEW.md`.
- [ ] Consolidate duplicate notification docs into `NOTIFICATIONS_TESTING_GUIDE.md`.
- [ ] Document `DELETE`, `clear-all`, and `register-token` endpoints in testing guide.

## Recommended Next Steps

1. Fix `email_tasks.py` line 52: replace `sender._do_send(...)` with `sender.send(...)`, or add `_do_send()` to `EmailSender` preserving retry semantics.
2. Fix or remove `tests/test_notifications_use_celery.py` to match the actual `EmailSender` API.
3. Add `Notification.create_indexes()` and `DeviceToken.create_indexes()` to `init_db.py`.
4. Create `docs/NOTIFICATIONS_PRODUCTION_READINESS_REVIEW.md` to track these items.
5. Consolidate `NOTIFICATIONS_TESTING_GUIDE.md` and `NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` into one canonical guide.
6. Add `tests/test_notifications_api.py` covering the 7 inbox endpoints, ownership, filters, pagination, and error cases.

## Notes

- This review is code-level only (no live environment penetration testing).
- Notification endpoints mutate state and trigger side effects (email sends, WebSocket broadcasts, MongoDB writes, FCM pushes); tests should mock external I/O and assert on created records and broadcast calls.
