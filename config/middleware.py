import json
from hmac import compare_digest
from django.conf import settings
from django.http import JsonResponse


class SecurityHeadersMiddleware:
    """
    Middleware to add security headers to all responses
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Prevent clickjacking attacks
        response['X-Frame-Options'] = 'DENY'
        
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS protection
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Enforce HTTPS (only in production)
        if not request.get_host().startswith('localhost'):
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        # Strict API-first CSP.
        # This backend serves JSON APIs; it does not require inline/eval script execution.
        is_local = request.get_host().startswith('localhost') or request.get_host().startswith('127.0.0.1')

        if is_local:
            # Keep localhost connect targets for local tooling, while still blocking script execution.
            response['Content-Security-Policy'] = (
                "default-src 'none'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'; "
                "form-action 'none'; "
                "object-src 'none'; "
                "script-src 'none'; "
                "style-src 'none'; "
                "img-src 'self' data: http://localhost:*; "
                "font-src 'none'; "
                "connect-src 'self' http://localhost:* ws://localhost:*; "
                "frame-src 'none'; "
                "manifest-src 'none'; "
                "worker-src 'none'"
            )
        else:
            response['Content-Security-Policy'] = (
                "default-src 'none'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'; "
                "form-action 'none'; "
                "object-src 'none'; "
                "script-src 'none'; "
                "style-src 'none'; "
                "img-src 'self' data: https:; "
                "font-src 'none'; "
                "connect-src 'self'; "
                "frame-src 'none'; "
                "manifest-src 'none'; "
                "worker-src 'none'"
            )
        
        # Referrer Policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions Policy
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

        # Cross-origin isolation / Spectre hardening
        response['Cross-Origin-Opener-Policy'] = 'same-origin'
        response['Cross-Origin-Resource-Policy'] = 'same-site'
        response['Cross-Origin-Embedder-Policy'] = 'require-corp'
        response['Origin-Agent-Cluster'] = '?1'
        
        return response


class CSRFSameSiteTokenMiddleware:
    """
    Enforce CSRF token checks for unsafe API methods when a CSRF cookie exists.

    This keeps Bearer-token API clients working (no cookie, no CSRF check),
    while protecting browser cookie-based flows with double-submit token checks.
    """

    SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._requires_csrf_validation(request):
            cookie_name = getattr(settings, 'CSRF_COOKIE_NAME', 'csrftoken')
            csrf_cookie = request.COOKIES.get(cookie_name, '')

            if csrf_cookie:
                csrf_header = (
                    request.META.get('HTTP_X_CSRFTOKEN')
                    or request.META.get('HTTP_X_CSRF_TOKEN')
                    or request.POST.get('csrfmiddlewaretoken')
                    or ''
                )

                if not csrf_header:
                    return JsonResponse(
                        {
                            'status': 'error',
                            'message': 'CSRF token required',
                            'code': 'csrf_token_missing',
                        },
                        status=403,
                    )

                if not compare_digest(csrf_header, csrf_cookie):
                    return JsonResponse(
                        {
                            'status': 'error',
                            'message': 'Invalid CSRF token',
                            'code': 'csrf_token_invalid',
                        },
                        status=403,
                    )

        return self.get_response(request)

    def _requires_csrf_validation(self, request):
        return request.path.startswith('/api/') and request.method not in self.SAFE_METHODS


class NoSQLInjectionGuardMiddleware:
    """
    Block suspicious Mongo operator-style payload keys at the API edge.

    This provides a centralized defense-in-depth check against NoSQL injection
    attempts such as:
        {"email": {"$ne": ""}}
        {"profile.name": "x"}
    """

    SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
    API_PREFIX = '/api/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.API_PREFIX) and request.method not in self.SAFE_METHODS:
            blocked_field = self._find_disallowed_field(request)
            if blocked_field:
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'Potential NoSQL injection payload detected',
                        'errors': {
                            blocked_field: (
                                'Mongo-style operator keys (starting with "$") '
                                'or dotted keys are not allowed'
                            )
                        },
                        'validation_feedback': {
                            'error_count': 1,
                            'fields': [blocked_field],
                            'issues': [
                                {
                                    'field': blocked_field,
                                    'message': (
                                        'Mongo-style operator keys are not permitted '
                                        'in request payloads'
                                    ),
                                    'code': 'nosql_injection_detected',
                                    'hint': 'Use plain scalar values (string/number/boolean) only.',
                                }
                            ],
                        },
                    },
                    status=400,
                )

        return self.get_response(request)

    def _find_disallowed_field(self, request):
        """
        Inspect query/body payload for operator-like keys.
        Returns the first offending field path, or None.
        """
        query_hit = self._scan_flat_mapping(request.GET, root='query')
        if query_hit:
            return query_hit

        content_type = (request.META.get('CONTENT_TYPE') or '').split(';', 1)[0].strip().lower()

        if content_type == 'application/json':
            raw_body = request.body
            if not raw_body:
                return None
            try:
                payload = json.loads(raw_body.decode(request.encoding or 'utf-8'))
            except (ValueError, UnicodeDecodeError):
                # Let normal JSON parsing/validation handle malformed payloads.
                return None
            return self._scan_recursive(payload, root='body')

        if content_type in {'application/x-www-form-urlencoded', 'multipart/form-data'}:
            form_hit = self._scan_flat_mapping(request.POST, root='body')
            if form_hit:
                return form_hit
            file_hit = self._scan_flat_mapping(request.FILES, root='files')
            if file_hit:
                return file_hit

        return None

    def _scan_recursive(self, value, root):
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                field_path = f"{root}.{key_text}" if root else key_text
                if self._is_disallowed_key(key_text):
                    return field_path
                child_hit = self._scan_recursive(child, field_path)
                if child_hit:
                    return child_hit
            return None

        if isinstance(value, list):
            for index, child in enumerate(value):
                child_hit = self._scan_recursive(child, f"{root}[{index}]")
                if child_hit:
                    return child_hit
            return None

        return None

    def _scan_flat_mapping(self, mapping, root):
        for key in mapping.keys():
            key_text = str(key)
            if self._is_disallowed_key(key_text):
                return f"{root}.{key_text}" if root else key_text
        return None

    @staticmethod
    def _is_disallowed_key(key):
        normalized = str(key).strip()
        return normalized.startswith('$') or '.' in normalized
