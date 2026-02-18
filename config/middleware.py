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
