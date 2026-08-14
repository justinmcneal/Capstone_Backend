"""Bounded, failure-safe HTTP boundary for AI providers."""

import logging
import threading
import time
from typing import ClassVar

import requests
from django.conf import settings

logger = logging.getLogger('ai_assistant')


class ProviderCircuitOpen(requests.RequestException):
    """Raised when the local provider circuit is open."""


class ProviderConcurrencyExceeded(requests.RequestException):
    """Raised when all per-process provider request slots are occupied."""


class _CircuitBreaker:
    def __init__(self):
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = None

    def allow(self):
        with self._lock:
            if self._opened_at is None:
                return True
            recovery = settings.AI_ASSISTANT_CIRCUIT_RECOVERY_SECONDS
            if time.monotonic() - self._opened_at >= recovery:
                self._opened_at = None
                self._failures = 0
                return True
            return False

    def success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= settings.AI_ASSISTANT_CIRCUIT_FAILURE_THRESHOLD:
                self._opened_at = time.monotonic()

    def state(self):
        return 'closed' if self.allow() else 'open'

    def reset(self):
        self.success()


class _GuardedStreamingResponse:
    """Keep a concurrency permit until a streaming response is consumed."""

    def __init__(self, response, release):
        self._response = response
        self._release = release
        self._released = False

    def __getattr__(self, name):
        return getattr(self._response, name)

    def _release_once(self):
        if not self._released:
            self._released = True
            self._release()

    def iter_lines(self, *args, **kwargs):
        try:
            yield from self._response.iter_lines(*args, **kwargs)
        finally:
            self._release_once()

    def close(self):
        try:
            return self._response.close()
        finally:
            self._release_once()


class ProviderSession:
    """Requests-compatible session enforcing timeout, retry and load policy."""

    transient_statuses: ClassVar[set[int]] = {429, 502, 503, 504}

    def __init__(self):
        self._session = requests.Session()
        self._circuit = _CircuitBreaker()
        self._semaphore = None
        self._semaphore_limit = None
        self._semaphore_lock = threading.Lock()

    def _slots(self):
        limit = settings.AI_ASSISTANT_MAX_CONCURRENT_REQUESTS
        with self._semaphore_lock:
            if self._semaphore is None or self._semaphore_limit != limit:
                self._semaphore = threading.BoundedSemaphore(limit)
                self._semaphore_limit = limit
            return self._semaphore

    def request(self, method, url, **kwargs):
        if not self._circuit.allow():
            raise ProviderCircuitOpen('AI provider circuit is open')

        slots = self._slots()
        if not slots.acquire(blocking=False):
            raise ProviderConcurrencyExceeded('AI provider concurrency limit reached')

        stream = bool(kwargs.get('stream'))
        kwargs['timeout'] = (
            settings.AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS,
            settings.AI_ASSISTANT_READ_TIMEOUT_SECONDS,
        )
        # Retrying paid/non-idempotent POSTs could duplicate usage. Only safe
        # readiness GETs receive bounded retries.
        attempts = settings.AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS if method.upper() == 'GET' else 1
        try:
            for attempt in range(attempts):
                try:
                    response = self._session.request(method, url, **kwargs)
                except (requests.ConnectionError, requests.Timeout):
                    self._circuit.failure()
                    if attempt + 1 >= attempts:
                        raise
                else:
                    if response.status_code in self.transient_statuses:
                        self._circuit.failure()
                        if attempt + 1 < attempts:
                            response.close()
                        else:
                            return self._finish_response(response, stream, slots)
                    else:
                        self._circuit.success()
                        return self._finish_response(response, stream, slots)
                time.sleep(settings.AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS * (2 ** attempt))
        except Exception:
            slots.release()
            raise

    @staticmethod
    def _finish_response(response, stream, slots):
        if stream:
            return _GuardedStreamingResponse(response, slots.release)
        slots.release()
        return response

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)

    def circuit_state(self):
        return self._circuit.state()

    def reset_for_tests(self):
        self._circuit.reset()


provider_session = ProviderSession()
