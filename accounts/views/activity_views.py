import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.models.activity import ActiveSession, LoginActivity
from accounts.services.security_event_service import SecurityEventService
from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS
from accounts.utils.request_utils import get_client_ip
from accounts.utils.response_helpers import APIResponseHelper

logger = logging.getLogger("authentication")


class ActiveSessionsView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    @staticmethod
    def _record_termination(request, details):
        from accounts.utils.user_detection import get_authenticated_user

        user, user_type = get_authenticated_user(request)
        if user:
            SecurityEventService.record(
                user=user,
                user_type=user_type,
                action="sessions_terminated",
                ip_address=get_client_ip(request),
                details=details,
            )

    def get(self, request):
        user_id = (
            str(request.user.customer_id)
            if hasattr(request.user, "customer_id")
            else str(request.user.id)
        )
        sessions = ActiveSession.find(
            {"user_id": user_id, "is_active": True}, sort=[("last_active", -1)]
        )
        data = [s.to_dict() for s in sessions]
        return APIResponseHelper.success_response(
            data=data, message="Active sessions retrieved"
        )

    def delete(self, request):
        session_id = request.data.get("session_id")
        user_id = (
            str(request.user.customer_id)
            if hasattr(request.user, "customer_id")
            else str(request.user.id)
        )

        revoke_all = request.data.get("revoke_all") is True
        keep_current = request.data.get("keep_current") is True
        current_session_id = getattr(request.user, "session_id", None)

        if revoke_all:
            from accounts.utils.token_utils import TokenUtils

            TokenUtils.revoke_all_sessions(
                user_id,
                request.user.role,
                except_session_id=current_session_id if keep_current else None,
            )
            self._record_termination(
                request,
                {"scope": "other_sessions" if keep_current else "all_sessions"},
            )
            return APIResponseHelper.success_response(
                message=(
                    "Other sessions terminated successfully"
                    if keep_current
                    else "All sessions terminated successfully"
                )
            )

        if not session_id:
            return APIResponseHelper.error_response(
                "session_id is required unless revoke_all is true"
            )

        try:
            from bson import ObjectId

            from accounts.utils.token_utils import TokenUtils

            # Prefer the public opaque session ID. ObjectId lookup remains only
            # for records created by the previous API contract.
            session = ActiveSession.find_one(
                {"session_id": str(session_id), "user_id": user_id}
            )
            if not session:
                try:
                    session = ActiveSession.find_one(
                        {"_id": ObjectId(session_id), "user_id": user_id}
                    )
                except (TypeError, ValueError):
                    session = None
            if not session:
                return APIResponseHelper.error_response(
                    "Session not found or not authorized", 404
                )

            if session.session_id:
                TokenUtils.revoke_session(
                    user_id, request.user.role, session.session_id
                )
            else:
                ActiveSession.update_many(
                    {"_id": session._id}, {"$set": {"is_active": False}}
                )

            self._record_termination(
                request,
                {"scope": "single_session", "session_id": str(session_id)},
            )

            return APIResponseHelper.success_response(
                message="Session terminated successfully"
            )
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Failed to terminate session: {e!s}")
            return APIResponseHelper.server_error_response(
                "Failed to terminate session"
            )


class LoginActivityView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user_id = (
            str(request.user.customer_id)
            if hasattr(request.user, "customer_id")
            else str(request.user.id)
        )
        activities = LoginActivity.find({"user_id": user_id}, limit=20)
        data = [a.to_dict() for a in activities]
        return APIResponseHelper.success_response(
            data=data, message="Login activity retrieved"
        )
