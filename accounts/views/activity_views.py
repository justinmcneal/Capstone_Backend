from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from accounts.authentication import CustomJWTAuthentication
from accounts.models.activity import ActiveSession, LoginActivity
from accounts.utils.response_helpers import APIResponseHelper
import logging

logger = logging.getLogger("authentication")

class ActiveSessionsView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.customer_id) if hasattr(request.user, 'customer_id') else str(request.user.id)
        sessions = ActiveSession.find({"user_id": user_id, "is_active": True}, sort=[("last_active", -1)])
        data = [s.to_dict() for s in sessions]
        return APIResponseHelper.success_response(data=data, message="Active sessions retrieved")

    def delete(self, request):
        session_id = request.data.get("session_id")
        user_id = str(request.user.customer_id) if hasattr(request.user, 'customer_id') else str(request.user.id)
        
        if not session_id:
            return APIResponseHelper.error_response("session_id is required")
            
        try:
            from bson import ObjectId
            from accounts.utils.token_utils import TokenUtils
            
            # Ensure the session belongs to the user
            session = ActiveSession.find_one({"_id": ObjectId(session_id), "user_id": user_id})
            if not session:
                return APIResponseHelper.error_response("Session not found or not authorized", 404)
                
            ActiveSession.update_many({"_id": ObjectId(session_id)}, {"$set": {"is_active": False}})
            
            # Blacklist the refresh token associated with the session
            if session.session_token:
                TokenUtils.blacklist_token(session.session_token)
                
            return APIResponseHelper.success_response(message="Session terminated successfully")
        except Exception as e:
            logger.error(f"Failed to terminate session: {str(e)}")
            return APIResponseHelper.server_error_response("Failed to terminate session")

class LoginActivityView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.customer_id) if hasattr(request.user, 'customer_id') else str(request.user.id)
        activities = LoginActivity.find({"user_id": user_id}, limit=20)
        data = [a.to_dict() for a in activities]
        return APIResponseHelper.success_response(data=data, message="Login activity retrieved")
