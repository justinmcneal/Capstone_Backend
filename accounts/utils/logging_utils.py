import logging

logger = logging.getLogger('authentication')


class RequestLogger:
    """Centralized logging utility for authentication requests"""
    
    @staticmethod
    def get_client_ip(request):
        """Extract client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @staticmethod
    def log_info(action, request, email=None, extra_data=None):
        """Log informational message with IP address"""
        ip = RequestLogger.get_client_ip(request)
        msg = f"{action}"
        if email:
            msg += f" for {email}"
        msg += f" from IP {ip}"
        if extra_data:
            msg += f" - {extra_data}"
        logger.info(msg)
    
    @staticmethod
    def log_warning(action, request, email=None, reason=None):
        """Log warning message with IP address"""
        ip = RequestLogger.get_client_ip(request)
        msg = f"{action}"
        if email:
            msg += f" for {email}"
        msg += f" from IP {ip}"
        if reason:
            msg += f": {reason}"
        logger.warning(msg)
    
    @staticmethod
    def log_error(action, request, error, email=None):
        """Log error message with IP address"""
        ip = RequestLogger.get_client_ip(request)
        msg = f"{action}"
        if email:
            msg += f" for {email}"
        msg += f" from IP {ip}: {str(error)}"
        logger.error(msg)
    
    @staticmethod
    def log_validation_failed(action, request):
        """Log validation failure"""
        RequestLogger.log_warning(f"{action} validation failed", request)
    
    @staticmethod
    def log_rate_limit_exceeded(request, email=None, seconds=None):
        """Log rate limit exceeded"""
        extra = f"{seconds} seconds remaining" if seconds else None
        RequestLogger.log_warning("Rate limit exceeded", request, email, extra)
