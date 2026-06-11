# WebSocket Testing Plan
**Project:** Capstone Backend — Real-Time Notification System  
**Protocol:** WebSocket over ASGI (Django Channels + Daphne)  
**Version:** 1.0  
**Date:** June 9, 2026  
**Author:** QA / Backend Team

---

## Table of Contents

1. [Overview](#1-overview)
2. [Environment Setup](#2-environment-setup)
3. [Pre-Test Checklist](#3-pre-test-checklist)
4. [Test Cases](#4-test-cases)
   - [TC-001: WebSocket Connection](#tc-001-websocket-connection)
   - [TC-002: JWT Authentication](#tc-002-jwt-authentication)
   - [TC-003: Real-Time Notification Delivery](#tc-003-real-time-notification-delivery)
   - [TC-004: Disconnection Handling](#tc-004-disconnection-handling)
   - [TC-005: Reconnection Behavior](#tc-005-reconnection-behavior)
   - [TC-006: Invalid Token Rejection](#tc-006-invalid-token-rejection)
   - [TC-007: Expired Token Handling](#tc-007-expired-token-handling)
   - [TC-008: Multi-Client Broadcast](#tc-008-multi-client-broadcast)
   - [TC-009: Role-Based Notification Routing](#tc-009-role-based-notification-routing)
   - [TC-010: Redis Channel Layer Failure](#tc-010-redis-channel-layer-failure)
5. [Test Execution Steps](#5-test-execution-steps)
6. [Expected Outcomes Summary](#6-expected-outcomes-summary)
7. [Error Reference](#7-error-reference)
8. [Sign-Off](#8-sign-off)

---

## 1. Overview

This document outlines the test plan for validating WebSocket functionality in the Capstone Backend system. The WebSocket implementation enables real-time notification delivery to authenticated users using Django Channels, Daphne ASGI server, and Redis as the channel layer backend.

### Scope

| In Scope | Out of Scope |
|---|---|
| WebSocket connection and handshake | REST API endpoints |
| JWT-based authentication | Database CRUD operations |
| Real-time notification broadcast | Frontend UI rendering |
| Connection lifecycle (open/close/error) | Celery background task internals |
| Role-based message routing | AWS S3 integration |
| Redis channel layer behavior | Blockchain / Web3 features |

### WebSocket Endpoint

```
ws://localhost:8000/ws/notifications/?token=<JWT_ACCESS_TOKEN>
```

---

## 2. Environment Setup

### 2.1 Required Services

| Service | Command | Port | Status Check |
|---|---|---|---|
| Redis | `redis-server.exe` | `6379` | `redis-cli ping` → `PONG` |
| Django/Daphne | `python manage.py runserver` | `8000` | Browser → `http://localhost:8000` |
| Frontend (optional) | `npm run dev` or `python -m http.server 5500` | `3000` / `5500` | Browser opens |

### 2.2 Required Tools

- **Browser DevTools** — Chrome or Firefox (F12 → Console)
- **Postman** — for REST API login to obtain JWT token
- **`websocket_test.html`** — custom test page in project root
- **Django Shell** — for triggering test notifications

### 2.3 Service Startup Order

```
1. Start Redis         →  redis-server.exe
2. Start Django        →  python manage.py runserver
3. Open test client    →  http://localhost:5500/websocket_test.html
4. Obtain JWT token    →  Login via frontend or Postman
```

---

## 3. Pre-Test Checklist

Complete all items before executing test cases.

- [x] Redis is running — confirmed with `redis-cli ping` returning `PONG`
- [x] Django server started — ASGI/Daphne mode confirmed in terminal output
- [x] `CHANNEL_LAYERS` configured in `settings.py` with Redis backend
- [x] `websocket_test.html` is accessible via `http://localhost:5500`
- [x] Valid JWT access token obtained via login
- [x] Django shell accessible — `python manage.py shell` runs without error
- [x] `notifications` app is installed and migrations are applied
- [x] No other process occupying port `6379` or `8000`

---

## 4. Test Cases

---

### TC-001: WebSocket Connection

| Field | Details |
|---|---|
| **Test ID** | TC-001 |
| **Category** | Connection |
| **Priority** | Critical |
| **Description** | Verify that a WebSocket connection can be established with a valid JWT token |

**Preconditions:**
- Redis and Django are running
- Valid JWT token is available

**Steps:**
1. Open `websocket_test.html` in the browser
2. Paste the JWT access token into the token field
3. Click **Connect**
4. Observe the connection status indicator

**Expected Result:**
```
✅ WebSocket connected!
Status: OPEN
```

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-002: JWT Authentication

| Field | Details |
|---|---|
| **Test ID** | TC-002 |
| **Category** | Authentication |
| **Priority** | Critical |
| **Description** | Verify that the WebSocket handshake validates the JWT token correctly |

**Preconditions:**
- Valid JWT token obtained from login

**Steps:**
1. Open browser DevTools → Network tab
2. Filter by **WS** (WebSocket)
3. Connect via `websocket_test.html` with valid token
4. Inspect the WebSocket handshake request headers

**Expected Result:**
- HTTP 101 Switching Protocols returned
- Connection upgraded to WebSocket
- No authentication error in Django terminal

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-003: Real-Time Notification Delivery

| Field | Details |
|---|---|
| **Test ID** | TC-003 |
| **Category** | Core Functionality |
| **Priority** | Critical |
| **Description** | Verify that a notification created via Django shell is delivered in real-time to the connected WebSocket client |

**Preconditions:**
- TC-001 passed (WebSocket connected)
- Django shell is open

**Steps:**
1. Ensure WebSocket is connected in `websocket_test.html`
2. Open a new terminal and run:
   ```
   python manage.py shell
   ```
3. In the shell, execute:
   ```python
   from notifications.services.notification_creator import create_and_broadcast_notification

   create_and_broadcast_notification(
       user_id="6a2038d4d8b3980ae57f1d1f",
       user_type="loan_officer",
       notification_type="test",
       subject="Test Notification",
       message="Real-time WebSocket test!",
       channel="in_app"
   )
   ```
4. Observe the `websocket_test.html` page immediately

**Expected Result:**
```json
📩 Message received: {
  "type": "notification",
  "subject": "Test Notification",
  "message": "Real-time WebSocket test!",
  "notification_type": "test"
}
```

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-004: Disconnection Handling

| Field | Details |
|---|---|
| **Test ID** | TC-004 |
| **Category** | Connection Lifecycle |
| **Priority** | High |
| **Description** | Verify that the server handles client disconnection gracefully |

**Steps:**
1. Connect via `websocket_test.html`
2. Click **Disconnect** (or close the browser tab)
3. Check Django terminal for disconnect log

**Expected Result:**
- Client console: `🔌 WebSocket closed: 1000`
- Django terminal: No unhandled exception; disconnect logged cleanly

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-005: Reconnection Behavior

| Field | Details |
|---|---|
| **Test ID** | TC-005 |
| **Category** | Connection Lifecycle |
| **Priority** | Medium |
| **Description** | Verify that a client can reconnect after disconnecting |

**Steps:**
1. Connect via `websocket_test.html`
2. Click **Disconnect**
3. Wait 3 seconds
4. Click **Connect** again with the same token
5. Trigger a notification via Django shell (see TC-003)

**Expected Result:**
- Reconnection succeeds with status `OPEN`
- Notification is delivered after reconnect

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-006: Invalid Token Rejection

| Field | Details |
|---|---|
| **Test ID** | TC-006 |
| **Category** | Security |
| **Priority** | Critical |
| **Description** | Verify that connections with an invalid or tampered JWT token are rejected |

**Steps:**
1. Open `websocket_test.html`
2. Enter a fake token: `invalidtoken123`
3. Click **Connect**
4. Observe connection result

**Expected Result:**
```
❌ WebSocket closed: 4001 (or 4003)
Reason: Authentication failed / Invalid token
```

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-007: Expired Token Handling

| Field | Details |
|---|---|
| **Test ID** | TC-007 |
| **Category** | Security |
| **Priority** | High |
| **Description** | Verify that an expired JWT token cannot establish a WebSocket connection |

**Steps:**
1. Obtain a JWT token
2. Wait for it to expire (or manually modify the `exp` claim)
3. Attempt to connect via `websocket_test.html`

**Expected Result:**
- Connection refused
- Close code: `4001` or equivalent
- Django logs: Token expired error

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-008: Multi-Client Broadcast

| Field | Details |
|---|---|
| **Test ID** | TC-008 |
| **Category** | Broadcast |
| **Priority** | High |
| **Description** | Verify that a notification is delivered to multiple connected clients for the same user |

**Steps:**
1. Open `websocket_test.html` in **two browser tabs**
2. Connect both tabs using the same JWT token
3. Trigger a notification via Django shell (see TC-003)
4. Observe both tabs

**Expected Result:**
- Both clients receive the notification simultaneously

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

### TC-009: Role-Based Notification Routing

| Field | Details |
|---|---|
| **Test ID** | TC-009 |
| **Category** | Business Logic |
| **Priority** | Medium |
| **Description** | Verify that notifications are routed only to the intended user role |

**Steps:**
1. Connect two clients with **different user roles** (e.g., `loan_officer` and `customer`)
2. Send a notification targeted only to `loan_officer`
3. Observe both clients

**Expected Result:**
- `loan_officer` client receives the notification
- `customer` client receives nothing

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** ___

---

### TC-010: Redis Channel Layer Failure

| Field | Details |
|---|---|
| **Test ID** | TC-010 |
| **Category** | Resilience |
| **Priority** | Medium |
| **Description** | Verify system behavior when Redis becomes unavailable during an active WebSocket session |

**Steps:**
1. Connect via `websocket_test.html`
2. Stop Redis: close the `redis-server.exe` terminal
3. Trigger a notification via Django shell
4. Observe the Django terminal and client

**Expected Result:**
- Django logs a Redis connection error
- Client does not crash; may show disconnection or timeout
- No unhandled server exception

**Actual Result:** _(fill during testing)_  
**Status:** `PASS` / `FAIL` / `BLOCKED`  
**Notes:** PASS

---

## 5. Test Execution Steps

### Step 1 — Start Services
```powershell
# Terminal 1: Start Redis
cd D:\Downloads\extensions\redis
.\redis-server.exe

# Terminal 2: Start Django
cd D:\Downloads\coding\Capstone\Sem1\Capstone_Backend
python manage.py runserver

# Terminal 3: Serve test HTML
cd D:\Downloads\coding\Capstone\Sem1\Capstone_Backend
python -m http.server 5500
```

### Step 2 — Obtain JWT Token
```
POST http://localhost:8000/api/auth/login/
Body: { "email": "...", "password": "..." }
Copy the "access" value from the response
```

### Step 3 — Open Test Client
```
http://localhost:5500/websocket_test.html
```

### Step 4 — Trigger Test Notification (Django Shell)
```powershell
# Terminal 4: Django shell
python manage.py shell
```
```python
from notifications.services.notification_creator import create_and_broadcast_notification

create_and_broadcast_notification(
    user_id="6a2038d4d8b3980ae57f1d1f",
    user_type="loan_officer",
    notification_type="test",
    subject="Test Notification",
    message="Real-time WebSocket test!",
    channel="in_app"
)
```

---

## 6. Expected Outcomes Summary

| Test ID | Test Name | Priority | Expected Status |
|---|---|---|---|
| TC-001 | WebSocket Connection | Critical | PASS |
| TC-002 | JWT Authentication | Critical | PASS |
| TC-003 | Real-Time Notification Delivery | Critical | PASS |
| TC-004 | Disconnection Handling | High | PASS |
| TC-005 | Reconnection Behavior | Medium | PASS |
| TC-006 | Invalid Token Rejection | Critical | PASS |
| TC-007 | Expired Token Handling | High | PASS |
| TC-008 | Multi-Client Broadcast | High | PASS |
| TC-009 | Role-Based Notification Routing | Medium | PASS |
| TC-010 | Redis Channel Layer Failure | Medium | PASS |

---

## 7. Error Reference

| Close Code | Meaning | Action |
|---|---|---|
| `1000` | Normal closure | Expected on manual disconnect |
| `1006` | Abnormal closure (no close frame) | Check if server crashed |
| `4001` | Authentication failed | Verify JWT token is valid |
| `4003` | Forbidden / Unauthorized | Check user role or permissions |
| `4004` | Not found | Verify WebSocket URL and routing |

### Common Issues

**Redis not running:**
```
Error: Error 111 connecting to localhost:6379. Connection refused.
Fix: Start redis-server.exe first
```

**Port already in use:**
```
Error: bind: An operation was attempted on something that is not a socket.
Fix: netstat -ano | findstr :6379  →  taskkill /PID <pid> /F
```

**ASGI not configured:**
```
Symptom: Server starts in WSGI mode instead of ASGI/Daphne
Fix: Ensure daphne is installed and ASGI_APPLICATION is set in settings.py
```

---

## 8. Sign-Off

| Role | Name | Date | Signature |
|---|---|---|---|
| Developer | | | |
| QA Tester | | | |
| Tech Lead | | | |

---

*This document is version-controlled. Update the version number and date for each revision.*