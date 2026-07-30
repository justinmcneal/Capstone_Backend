# Notifications Production Readiness Review

Date: 2026-07-29  
Scope: Static code review of `notifications/` and related inbox, email, WebSocket, push-notification, and assignment-event behavior.

## Executive Summary

The `notifications/` module provides an in-app notification inbox, role-scoped access control, template-based email delivery, optional Celery async sends, real-time WebSocket broadcasts via Django Channels, FCM push notifications, and assignment-lifecycle event notifications. Core functionality is implemented and covered by multiple existing test files. Previously identified Celery mismatches have been fixed: `email_tasks.py` now calls the existing `EmailSender.send()` method, and `tests/test_notifications_use_celery.py` matches the current implementation. Notification testing and implementation documentation has been consolidated into a single canonical guide. This review documents any remaining gaps and recommended next steps.

## High Priority Findings

 1. Dedicated inbox API test file added.
    - `tests/test_notifications_api.py` covers the 7 inbox endpoints with authenticated requests, role enforcement, filters, pagination edge cases, and failure modes.
    - **Status: DONE.**

 2. Documentation has been consolidated into a single canonical guide.
    - `docs/NOTIFICATIONS_TESTING_GUIDE.md` covers inbox API, WebSocket, FCM, assignment events, email templates, metrics, and smoke tests.
    - `docs/NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` and `docs/NOTIFICATIONS_METRICS.md` have been merged and removed.
    - **Status: DONE.**

 3. WebSocket consumer scope is narrow.
    - `NotificationConsumer` handles `ping` and `mark_read` only.
    - Risk: clients cannot mark-all-read, delete, or fetch unread count over WebSocket; they must fall back to REST.
    - **Status: NEEDS REVIEW.** (low priority; REST fallback is acceptable for now)

## Medium Priority Findings

 1. WebSocket consumer scope is narrow.
    - `NotificationConsumer` handles `ping` and `mark_read` only.
    - Risk: clients cannot mark-all-read, delete, or fetch unread count over WebSocket; they must fall back to REST.
    - **Status: NEEDS REVIEW.** (low priority; REST fallback is acceptable for now)

## Low Priority Findings

No remaining low-priority findings.

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

- No notifications production-readiness review existed prior to this document.
- `tests/test_notifications_api.py` was added with dedicated inbox endpoint tests.
- Documentation consolidated into `docs/NOTIFICATIONS_TESTING_GUIDE.md`.
- `NOTIFICATIONS_IMPLEMENTATION_AND_TESTING_GUIDE.md` and `NOTIFICATIONS_METRICS.md` merged and removed.
- Celery task fixed to call existing `EmailSender.send()`.
- Celery tests rewritten to match actual `EmailSender` API.
- `Notification` and `DeviceToken` indexes bootstrapped in `init_db.py`.

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
 - [x] Consolidate duplicate notification docs into `NOTIFICATIONS_TESTING_GUIDE.md`.
 - [x] Document `DELETE`, `clear-all`, and `register-token` endpoints in testing guide.

## Notes

- This review is code-level only (no live environment penetration testing).
- Notification endpoints mutate state and trigger side effects (email sends, WebSocket broadcasts, MongoDB writes, FCM pushes); tests should mock external I/O and assert on created records and broadcast calls.
