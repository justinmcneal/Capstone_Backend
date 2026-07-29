# WebSocket Real-Time Notifications Implementation Plan

## Overview
Add WebSocket support to enable real-time push notifications for the web application while maintaining the existing REST API for mobile clients. This implementation uses Django Channels with Redis as the channel layer.

---

## Architecture Summary

### Current State
- REST API polling-based notification system (`/api/notifications/`)
- MongoDB storage for notification persistence
- Support for email and in-app notifications
- Endpoints: list, mark read, mark all read, unread count, delete

### Target State
- **Web**: WebSocket connections for real-time push notifications
- **Mobile**: Continue using existing REST API (no changes)
- Unified notification creation service that broadcasts to both channels
- Redis-backed channel layer for WebSocket message distribution

---

## Technology Stack

### Backend Dependencies
```
channels>=4.0.0              # Django WebSocket support
channels-redis>=4.2.0        # Redis channel layer
daphne>=4.0.0               # ASGI server for WebSockets
```

### Infrastructure
- **Redis**: Channel layer backend (can reuse existing Redis for Celery)
- **ASGI Server**: Daphne (production) or Uvicorn (development)

---

## Implementation Phases

## Phase 1: Django Channels Setup

### 1.1 Install Dependencies
```bash
pip install channels>=4.0.0 channels-redis>=4.2.0 daphne>=4.0.0
pip freeze > requirements.txt
```

### 1.2 Configure Django Settings (`config/settings.py`)
```python
INSTALLED_APPS = [
    'daphne',  # Must be at the top
    'django.contrib.admin',
    # ... other apps
    'channels',
    # ... rest of apps
]

# ASGI Application
ASGI_APPLICATION = 'config.asgi.application'

# Channel Layers Configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [(os.environ.get('REDIS_HOST', 'localhost'), 6379)],
        },
    },
}

# WebSocket settings
WEBSOCKET_ENABLED = os.environ.get('WEBSOCKET_ENABLED', 'true').lower() == 'true'
```

### 1.3 Create ASGI Configuration (`config/asgi.py`)
```python
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

from notifications.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
```

### 1.4 Update Environment Variables (`.env`)
```
# WebSocket Configuration
WEBSOCKET_ENABLED=true
REDIS_HOST=localhost  # or your Redis host
```

---

## Phase 2: WebSocket Authentication Middleware

### 2.1 Create JWT WebSocket Middleware (`notifications/middleware.py`)
```python
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from accounts.models import Customer, LoanOfficer, Admin

class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom middleware to authenticate WebSocket connections using JWT tokens.
    Token can be passed via:
    - Query parameter: ?token=<jwt_token>
    - Subprotocol header: Sec-WebSocket-Protocol: access_token, <jwt_token>
    """
    
    async def __call__(self, scope, receive, send):
        # Extract token from query string or headers
        token = None
        query_string = scope.get('query_string', b'').decode()
        if 'token=' in query_string:
            token = query_string.split('token=')[1].split('&')[0]
        
        # Fallback to subprotocol header
        if not token:
            headers = dict(scope.get('headers', []))
            subprotocols = headers.get(b'sec-websocket-protocol', b'').decode()
            if 'access_token' in subprotocols and ',' in subprotocols:
                token = subprotocols.split(',')[1].strip()
        
        # Authenticate user
        scope['user'] = await self.get_user_from_token(token)
        
        return await super().__call__(scope, receive, send)
    
    @database_sync_to_async
    def get_user_from_token(self, token):
        if not token:
            return AnonymousUser()
        
        try:
            access_token = AccessToken(token)
            user_id = access_token.get('user_id')
            role = access_token.get('role', 'customer')
            
            # Fetch user based on role
            if role == 'customer':
                return Customer.objects.get(customer_id=user_id)
            elif role in ['loan_officer', 'admin', 'super_admin']:
                return LoanOfficer.objects.get(officer_id=user_id)
            
        except Exception:
            pass
        
        return AnonymousUser()
```

---

## Phase 3: WebSocket Consumer

### 3.1 Create Notification Consumer (`notifications/consumers.py`)
```python
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger('notifications')

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications.
    
    Connection URL: ws://domain/ws/notifications/
    
    Client receives messages in format:
    {
        "type": "notification",
        "data": {
            "id": "...",
            "notification_type": "...",
            "subject": "...",
            "message": "...",
            "created_at": "...",
            ...
        }
    }
    """
    
    async def connect(self):
        user = self.scope.get('user')
        
        # Reject unauthenticated connections
        if not user or user.is_anonymous:
            await self.close(code=4001)
            return
        
        # Create user-specific group name
        self.user_id = str(getattr(user, 'customer_id', '') or getattr(user, 'officer_id', ''))
        self.user_group = f"notifications_{self.user_id}"
        
        # Join user's notification group
        await self.channel_layer.group_add(
            self.user_group,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"WebSocket connected: user={self.user_id}")
        
        # Send initial unread count
        unread_count = await self.get_unread_count(user)
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'data': {'unread_count': unread_count}
        }))
    
    async def disconnect(self, close_code):
        # Leave user's notification group
        if hasattr(self, 'user_group'):
            await self.channel_layer.group_discard(
                self.user_group,
                self.channel_name
            )
            logger.info(f"WebSocket disconnected: user={self.user_id}, code={close_code}")
    
    async def receive(self, text_data):
        """
        Handle incoming WebSocket messages from client.
        Supported commands:
        - {"action": "ping"} -> responds with pong
        - {"action": "mark_read", "notification_id": "..."}
        """
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }))
            
            elif action == 'mark_read':
                notification_id = data.get('notification_id')
                success = await self.mark_notification_read(notification_id)
                await self.send(text_data=json.dumps({
                    'type': 'mark_read_response',
                    'success': success,
                    'notification_id': notification_id
                }))
        
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))
    
    async def notification_message(self, event):
        """
        Handle notification broadcast from channel layer.
        Called when a message is sent to the user's group.
        """
        notification_data = event.get('data', {})
        
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'data': notification_data
        }))
    
    @database_sync_to_async
    def get_unread_count(self, user):
        from notifications.models.notification import get_db, Notification
        from notifications.views.notification_views import _build_notification_owner_query
        
        db = get_db()
        collection = db[Notification.collection_name]
        unread_query = _build_notification_owner_query(user)
        unread_query['status'] = {'$nin': ['read']}
        return collection.count_documents(unread_query)
    
    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from bson import ObjectId
        from notifications.models.notification import get_db, Notification
        from datetime import datetime, timezone
        
        try:
            db = get_db()
            collection = db[Notification.collection_name]
            result = collection.update_one(
                {'_id': ObjectId(notification_id), 'user_id': self.user_id},
                {'$set': {'status': 'read', 'read_at': datetime.now(timezone.utc)}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error marking notification read: {e}")
            return False
```

---

## Phase 4: WebSocket Routing

### 4.1 Create WebSocket URL Routing (`notifications/routing.py`)
```python
from django.urls import re_path
from notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    re_path(r'ws/notifications/$', NotificationConsumer.as_asgi()),
]
```

---

## Phase 5: Notification Broadcasting Service

### 5.1 Create WebSocket Broadcast Helper (`notifications/services/websocket_service.py`)
```python
import json
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings

logger = logging.getLogger('notifications')

def broadcast_notification_to_user(user_id, notification_data):
    """
    Broadcast a notification to a specific user via WebSocket.
    
    Args:
        user_id: User identifier (customer_id or officer_id)
        notification_data: Dictionary containing notification details
    """
    if not settings.WEBSOCKET_ENABLED:
        return
    
    try:
        channel_layer = get_channel_layer()
        user_group = f"notifications_{user_id}"
        
        async_to_sync(channel_layer.group_send)(
            user_group,
            {
                'type': 'notification_message',
                'data': notification_data
            }
        )
        
        logger.info(f"Notification broadcast to user {user_id} via WebSocket")
    
    except Exception as e:
        logger.error(f"Failed to broadcast notification via WebSocket: {e}")


def serialize_notification_for_ws(notification):
    """
    Serialize a Notification model instance for WebSocket transmission.
    """
    return {
        'id': notification.id,
        'notification_type': notification.notification_type,
        'subject': notification.subject,
        'message': notification.message,
        'related_type': notification.related_type,
        'related_id': str(notification.related_id) if notification.related_id else None,
        'channel': notification.channel,
        'status': notification.status,
        'is_read': notification.status == 'read',
        'created_at': notification.created_at.isoformat() if notification.created_at else None,
    }
```

### 5.2 Update Notification Creation Service (`notifications/services/notification_creator.py` - NEW FILE)
```python
"""
Unified notification creation service that handles both persistence and broadcasting.
"""
import logging
from notifications.models.notification import Notification
from notifications.services.websocket_service import (
    broadcast_notification_to_user,
    serialize_notification_for_ws
)

logger = logging.getLogger('notifications')

def create_and_broadcast_notification(
    user_id,
    user_type,
    notification_type,
    subject,
    message,
    recipient_email='',
    recipient_name='',
    related_type=None,
    related_id=None,
    channel='in_app'
):
    """
    Create a notification and broadcast it to connected WebSocket clients.
    
    This is the central notification creation function that should be used
    throughout the application.
    
    Returns:
        Notification: The created notification instance
    """
    # Create and persist notification
    notification = Notification(
        user_id=str(user_id),
        user_type=user_type,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        notification_type=notification_type,
        subject=subject,
        message=message,
        related_type=related_type,
        related_id=related_id,
        channel=channel,
        status='sent',
    )
    notification.save()
    
    logger.info(f"Created notification {notification.id} for user {user_id}")
    
    # Broadcast to WebSocket (web clients only)
    notification_data = serialize_notification_for_ws(notification)
    broadcast_notification_to_user(user_id, notification_data)
    
    return notification
```

### 5.3 Update Existing Notification Creation Points
Identify all places where `Notification()` is instantiated and replace with `create_and_broadcast_notification()`:

**Common locations to update:**
- `loans/services/*.py` - Loan status change notifications
- `documents/services/*.py` - Document review notifications  
- `accounts/services/*.py` - Account-related notifications
- Any Celery tasks that create notifications

**Example migration:**
```python
# BEFORE
notification = Notification(
    user_id=str(customer.customer_id),
    user_type='customer',
    notification_type='loan_approved',
    subject='Loan Approved',
    message=f'Your loan application #{loan_id} has been approved!',
    related_type='loan',
    related_id=loan_id,
    channel='in_app'
)
notification.save()

# AFTER
from notifications.services.notification_creator import create_and_broadcast_notification

create_and_broadcast_notification(
    user_id=customer.customer_id,
    user_type='customer',
    notification_type='loan_approved',
    subject='Loan Approved',
    message=f'Your loan application #{loan_id} has been approved!',
    related_type='loan',
    related_id=loan_id,
    channel='in_app'
)
```

---

## Phase 6: Frontend Integration Guide

### 6.1 WebSocket Client Connection (JavaScript)
```javascript
class NotificationWebSocket {
    constructor(token) {
        this.token = token;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
    }
    
    connect() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/notifications/?token=${this.token}`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket closed');
            this.attemptReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    handleMessage(message) {
        switch(message.type) {
            case 'connection_established':
                this.updateBadge(message.data.unread_count);
                break;
            
            case 'notification':
                this.displayNotification(message.data);
                this.updateBadge(); // Fetch new count
                break;
            
            case 'pong':
                // Handle heartbeat response
                break;
        }
    }
    
    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            setTimeout(() => {
                console.log(`Reconnecting... (${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
                this.reconnectAttempts++;
                this.connect();
            }, this.reconnectDelay * Math.pow(2, this.reconnectAttempts));
        }
    }
    
    displayNotification(notification) {
        // Show browser notification or in-app toast
        if (Notification.permission === 'granted') {
            new Notification(notification.subject, {
                body: notification.message,
                icon: '/static/notification-icon.png'
            });
        }
        
        // Update notification bell dropdown
        this.addToNotificationList(notification);
    }
    
    updateBadge(count = null) {
        if (count !== null) {
            document.getElementById('notification-badge').textContent = count;
        } else {
            // Fetch from API
            fetch('/api/notifications/unread-count/')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('notification-badge').textContent = data.data.unread_count;
                });
        }
    }
    
    markAsRead(notificationId) {
        this.ws.send(JSON.stringify({
            action: 'mark_read',
            notification_id: notificationId
        }));
    }
    
    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Initialize on login
const notificationWS = new NotificationWebSocket(accessToken);
notificationWS.connect();
```

### 6.2 Fallback Strategy for Connection Failures
```javascript
// Detect if WebSocket connection fails and fallback to polling
let wsConnected = false;
let pollingInterval = null;

notificationWS.ws.onopen = () => {
    wsConnected = true;
    clearInterval(pollingInterval); // Stop polling if WS connects
};

notificationWS.ws.onclose = () => {
    wsConnected = false;
    // Fallback to polling every 30 seconds
    pollingInterval = setInterval(() => {
        fetch('/api/notifications/unread-count/')
            .then(res => res.json())
            .then(data => updateBadge(data.data.unread_count));
    }, 30000);
};
```

---

## Phase 7: Testing Strategy

### 7.1 Unit Tests (`tests/test_websocket_notifications.py`)
```python
import pytest
from channels.testing import WebsocketCommunicator
from config.asgi import application
from notifications.services.notification_creator import create_and_broadcast_notification

@pytest.mark.asyncio
@pytest.mark.django_db
async def test_websocket_connection_with_valid_token():
    """Test WebSocket connection with valid JWT token"""
    # Create test user and generate token
    # ...
    
    communicator = WebsocketCommunicator(
        application,
        f"/ws/notifications/?token={valid_token}"
    )
    connected, _ = await communicator.connect()
    assert connected
    
    # Receive connection confirmation
    response = await communicator.receive_json_from()
    assert response['type'] == 'connection_established'
    
    await communicator.disconnect()

@pytest.mark.asyncio
async def test_websocket_rejects_invalid_token():
    """Test WebSocket connection rejection with invalid token"""
    communicator = WebsocketCommunicator(
        application,
        "/ws/notifications/?token=invalid_token"
    )
    connected, close_code = await communicator.connect()
    assert not connected
    assert close_code == 4001

@pytest.mark.asyncio
@pytest.mark.django_db
async def test_notification_broadcast():
    """Test notification is broadcasted to connected WebSocket client"""
    # Setup: Connect WebSocket
    # ...
    
    # Create notification
    notification = create_and_broadcast_notification(
        user_id=test_user.customer_id,
        user_type='customer',
        notification_type='test',
        subject='Test Notification',
        message='This is a test',
        channel='in_app'
    )
    
    # Verify WebSocket receives the notification
    response = await communicator.receive_json_from(timeout=2)
    assert response['type'] == 'notification'
    assert response['data']['id'] == notification.id
    
    await communicator.disconnect()
```

### 7.2 Integration Tests
- Test notification creation triggers WebSocket broadcast
- Test multiple concurrent WebSocket connections per user
- Test connection recovery and reconnection
- Test mark-as-read from WebSocket vs REST API sync

### 7.3 Manual Testing Checklist
- [ ] WebSocket connects successfully with valid JWT
- [ ] WebSocket rejects connection with invalid/expired JWT
- [ ] Real-time notifications appear instantly without refresh
- [ ] Notification bell badge updates in real-time
- [ ] Mark as read syncs between WebSocket and REST API
- [ ] Connection reconnects after network interruption
- [ ] Mobile app continues working with REST API (no regression)
- [ ] Multiple browser tabs receive same notifications
- [ ] Graceful fallback to polling if WebSocket fails

---

## Phase 8: Deployment Configuration

### 8.1 Update Procfile (Railway/Heroku)
```
web: daphne -b 0.0.0.0 -p $PORT config.asgi:application
worker: celery -A config worker --loglevel=info
beat: celery -A config beat --loglevel=info
```

### 8.2 NGINX Configuration (if using reverse proxy)
```nginx
location /ws/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebSocket timeout
    proxy_read_timeout 86400;
}
```

### 8.3 Environment Variables for Production
```
WEBSOCKET_ENABLED=true
REDIS_HOST=your-redis-host.cloud
DJANGO_SETTINGS_MODULE=config.settings
```

---

## Phase 9: Monitoring & Observability

### 9.1 Logging Enhancement
Add structured logging for WebSocket events:
```python
# In consumer
logger.info(
    "WebSocket connection",
    extra={
        'event': 'ws_connect',
        'user_id': self.user_id,
        'channel_name': self.channel_name
    }
)
```

### 9.2 Metrics to Track
- Active WebSocket connections count
- Notification broadcast success rate
- Average notification delivery latency
- WebSocket reconnection rate
- Redis channel layer health

### 9.3 Health Check Endpoint
```python
# In config/views.py or create new health check app
from channels.layers import get_channel_layer

async def websocket_health(request):
    """Check if channel layer is accessible"""
    try:
        channel_layer = get_channel_layer()
        await channel_layer.send('health_check', {'type': 'ping'})
        return JsonResponse({'status': 'healthy', 'websocket': 'ok'})
    except Exception as e:
        return JsonResponse({'status': 'unhealthy', 'error': str(e)}, status=503)
```

---

## Phase 10: Documentation Updates

### 10.1 API Documentation Updates
Add WebSocket documentation to existing API docs:

**WebSocket Endpoint:**
```
ws://domain/ws/notifications/?token=<JWT_ACCESS_TOKEN>

Connection:
- Requires valid JWT access token
- Token can be passed via query parameter or Sec-WebSocket-Protocol header

Message Types (Server -> Client):
- connection_established: Sent on successful connection with initial unread count
- notification: Real-time notification push
- pong: Response to ping heartbeat

Message Types (Client -> Server):
- ping: Heartbeat to keep connection alive
- mark_read: Mark notification as read via WebSocket
```

### 10.2 Developer Onboarding Guide
Create `docs/websocket_developer_guide.md` covering:
- How to create notifications that broadcast
- WebSocket consumer architecture
- Testing WebSocket functionality locally
- Troubleshooting common issues

---

## Migration & Rollout Strategy

### Phase A: Pre-Deployment (Development)
1. Install dependencies in dev environment
2. Configure Django Channels and Redis
3. Implement WebSocket consumer and routing
4. Write and run unit tests
5. Manual testing with frontend prototype

### Phase B: Staging Deployment
1. Deploy to staging with feature flag `WEBSOCKET_ENABLED=false`
2. Verify application starts successfully
3. Enable WebSocket: `WEBSOCKET_ENABLED=true`
4. Test with staging frontend
5. Load test with multiple concurrent connections

### Phase C: Production Rollout
1. Deploy backend with WebSocket support (feature flag OFF)
2. Monitor for any regressions in REST API
3. Deploy frontend with WebSocket client code (with fallback)
4. Enable WebSocket: `WEBSOCKET_ENABLED=true`
5. Monitor connection metrics and error rates
6. Gradually roll out to users (percentage-based if possible)

### Phase D: Post-Deployment
1. Monitor WebSocket connection stability for 1 week
2. Collect user feedback on real-time notification experience
3. Optimize reconnection logic based on metrics
4. Document any production issues and resolutions

---

## Rollback Plan

If critical issues arise:
1. Set `WEBSOCKET_ENABLED=false` (fallback to REST API polling)
2. Frontend automatically switches to polling mode
3. No data loss - all notifications still persist in MongoDB
4. Investigate issues in staging environment
5. Deploy fix and re-enable

---

## Security Considerations

### Authentication
- ✅ JWT validation on WebSocket connection
- ✅ User-specific notification groups (no cross-user leaks)
- ✅ Connection rejection for invalid/expired tokens

### Authorization
- ✅ Users only receive notifications intended for them
- ✅ User ID from JWT token, not client-provided
- ✅ MongoDB queries filtered by authenticated user

### Rate Limiting
- Consider WebSocket connection rate limits per IP
- Implement message rate limiting in consumer (`receive` method)

### Input Validation
- Validate all incoming WebSocket messages
- Sanitize notification content before broadcasting

---

## Performance Optimization

### Connection Management
- Set reasonable connection timeout (e.g., 1 hour of inactivity)
- Implement heartbeat/ping-pong to detect dead connections
- Limit max connections per user (e.g., 5 devices)

### Broadcasting Optimization
- Use Redis pub/sub for efficient message distribution
- Batch notifications if high volume expected
- Consider notification priority levels

### Database Queries
- Ensure MongoDB indexes on `user_id` and `status` fields (already exist)
- Optimize unread count query (already efficient)

---

## Estimated Timeline

| Phase | Tasks | Duration |
|-------|-------|----------|
| 1 | Django Channels Setup | 2-3 hours |
| 2 | WebSocket Authentication | 3-4 hours |
| 3 | WebSocket Consumer | 4-5 hours |
| 4 | WebSocket Routing | 1 hour |
| 5 | Notification Broadcasting Service | 3-4 hours |
| 6 | Frontend Integration | 6-8 hours |
| 7 | Testing | 4-6 hours |
| 8 | Deployment Configuration | 2-3 hours |
| 9 | Monitoring Setup | 2-3 hours |
| 10 | Documentation | 2-3 hours |
| **Total** | | **29-40 hours** |

---

## Success Metrics

### Technical Metrics
- WebSocket connection success rate > 95%
- Notification delivery latency < 500ms
- Connection uptime > 99%
- Zero impact on mobile app performance

### User Experience Metrics
- Real-time notification display without page refresh
- Notification badge updates instantly
- Seamless fallback to polling if WebSocket unavailable

---

## Future Enhancements

1. **Push Notification Integration** - Browser push notifications for offline users
2. **Notification Preferences** - User settings for notification channels
3. **Typing Indicators** - Real-time status for admin/officer responses
4. **Read Receipts** - Track when notifications are viewed
5. **Notification Categories** - Filter by type in real-time
6. **Message Queue** - Queue notifications for offline users and deliver on reconnect

---

## Questions & Clarifications

Before implementation, confirm:
- [ ] Redis instance details (host, port, auth)
- [ ] Expected concurrent WebSocket connections (capacity planning)
- [ ] Browser support requirements (modern browsers only?)
- [ ] Mobile app platform details (to ensure no interference)
- [ ] Deployment infrastructure (Railway, AWS, GCP, etc.)

---

## References

- [Django Channels Documentation](https://channels.readthedocs.io/)
- [Channels Redis Layer](https://github.com/django/channels_redis)
- [WebSocket API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [JWT Authentication Best Practices](https://jwt.io/introduction)

---

**Document Version:** 1.0  
**Last Updated:** June 8, 2026  
**Author:** Josh