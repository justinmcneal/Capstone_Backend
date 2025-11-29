from rest_framework.response import Response
from rest_framework import status


class APIResponseHelper:
    """Helper class for consistent API responses"""
    
    @staticmethod
    def success_response(data=None, message=None, status_code=status.HTTP_200_OK):
        response_data = {'success': True}
        if message:
            response_data['message'] = message
        if data:
            response_data['data'] = data
        return Response(response_data, status=status_code)
    
    @staticmethod
    def error_response(message, error_code=status.HTTP_400_BAD_REQUEST):
        return Response({
            'success': False,
            'message': message
        }, status=error_code)
    
    @staticmethod
    def validation_error_response(errors):
        return Response({
            'success': False,
            'errors': errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    @staticmethod
    def server_error_response(message='An unexpected error occurred'):
        return Response({
            'success': False,
            'error': message
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
