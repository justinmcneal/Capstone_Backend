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
        
        # Content Security Policy - relaxed for development
        # In production, remove 'unsafe-eval' and localhost references
        is_development = request.get_host().startswith('localhost') or request.get_host().startswith('127.0.0.1')
        
        if is_development:
            # Relaxed CSP for development (allows Vite HMR, eval for dev tools)
            response['Content-Security-Policy'] = (
                "default-src 'self' http://localhost:* ws://localhost:*; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https: http://localhost:*; "
                "font-src 'self' data:; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "frame-src 'none'; "
                "manifest-src 'self'; "
                "worker-src 'self' blob:; "
                "connect-src 'self' http://localhost:* ws://localhost:*; "
                "frame-ancestors 'none'; object-src 'none'"
            )
        else:
            # Strict CSP for production
            response['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "frame-src 'none'; "
                "manifest-src 'self'; "
                "worker-src 'self' blob:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; object-src 'none'"
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
