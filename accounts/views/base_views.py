from rest_framework.views import APIView
from rest_framework import status
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.logging_utils import RequestLogger


class BaseAuthView(APIView):
    """
    Base view class with common error handling, logging, and response patterns
    All authentication views should inherit from this class
    """

    def handle_exception(self, exc):
        RequestLogger.log_error(
            action=self.__class__.__name__, request=self.request, error=exc
        )
        return super().handle_exception(exc)

    def log_validation_error(self, serializer):
        RequestLogger.log_validation_failed(
            action=self.__class__.__name__, request=self.request
        )
        return APIResponseHelper.validation_error_response(serializer.errors)

    def log_success(self, action, email=None, extra_data=None):
        RequestLogger.log_info(
            action=action, request=self.request, email=email, extra_data=extra_data
        )

    def log_failure(self, action, email=None, reason=None):
        RequestLogger.log_warning(
            action=action, request=self.request, email=email, reason=reason
        )

    def handle_rate_limit(self, email=None, seconds_remaining=None):
        RequestLogger.log_rate_limit_exceeded(
            request=self.request, email=email, seconds=seconds_remaining
        )
        message = (
            f"Too many attempts. Please try again in {seconds_remaining} seconds."
            if seconds_remaining
            else "Too many attempts."
        )
        return APIResponseHelper.error_response(
            message=message, error_code=status.HTTP_429_TOO_MANY_REQUESTS
        )

    def success_response(self, data=None, message=None, status_code=status.HTTP_200_OK):
        return APIResponseHelper.success_response(
            data=data, message=message, status_code=status_code
        )

    def error_response(self, message, error_code=status.HTTP_400_BAD_REQUEST):
        return APIResponseHelper.error_response(message=message, error_code=error_code)

    def server_error_response(self, message="An unexpected error occurred"):
        return APIResponseHelper.server_error_response(message)
