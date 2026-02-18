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
