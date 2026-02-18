from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ErrorDetail


VALIDATION_HINTS = {
    'required': 'Provide this required field.',
    'blank': 'Value cannot be blank.',
    'null': 'Value cannot be null.',
    'invalid': 'Use the expected format or data type.',
    'invalid_choice': 'Use one of the allowed values.',
    'max_length': 'Shorten this value to the allowed maximum length.',
    'min_length': 'Increase this value to meet minimum length.',
    'max_value': 'Use a smaller value.',
    'min_value': 'Use a larger value.',
}


def _default_hint_for_message(message):
    lower = message.lower()
    if 'at most' in lower or 'maximum' in lower:
        return VALIDATION_HINTS['max_length']
    if 'at least' in lower or 'minimum' in lower:
        return VALIDATION_HINTS['min_length']
    if 'format' in lower:
        return VALIDATION_HINTS['invalid']
    if 'valid choice' in lower:
        return VALIDATION_HINTS['invalid_choice']
    return VALIDATION_HINTS['invalid']


def _build_issue(path, error):
    if isinstance(error, ErrorDetail):
        message = str(error)
        code = error.code or 'invalid'
    else:
        message = str(error)
        code = 'invalid'

    hint = VALIDATION_HINTS.get(code) or _default_hint_for_message(message)
    return {
        'field': path or 'non_field_errors',
        'message': message,
        'code': code,
        'hint': hint,
    }


def _flatten_validation_errors(errors, path=''):
    issues = []

    if isinstance(errors, dict):
        for key, value in errors.items():
            next_path = f"{path}.{key}" if path else str(key)
            issues.extend(_flatten_validation_errors(value, next_path))
        return issues

    if isinstance(errors, (list, tuple)):
        for item in errors:
            # Keep list-level path for human-friendly field mapping.
            issues.extend(_flatten_validation_errors(item, path))
        return issues

    issues.append(_build_issue(path, errors))
    return issues


def build_validation_feedback(errors):
    """
    Convert serializer errors into normalized, machine-readable feedback.
    """
    if not isinstance(errors, (dict, list, tuple)):
        return None

    issues = _flatten_validation_errors(errors)
    if not issues:
        return None

    fields = []
    seen = set()
    for issue in issues:
        field = issue['field']
        if field in seen:
            continue
        seen.add(field)
        fields.append(field)

    return {
        'error_count': len(issues),
        'fields': fields,
        'issues': issues,
    }


class APIResponseHelper:
    """Helper class for consistent API responses"""
    
    @staticmethod
    def success_response(data=None, message=None, status_code=status.HTTP_200_OK):
        response_data = {'status': 'success'}
        if message:
            response_data['message'] = message
        if data:
            response_data['data'] = data
        return Response(response_data, status=status_code)
    
    @staticmethod
    def error_response(message, error_code=status.HTTP_400_BAD_REQUEST):
        return Response({
            'status': 'error',
            'message': message
        }, status=error_code)
    
    @staticmethod
    def validation_error_response(errors):
        response_data = {
            'status': 'error',
            'errors': errors,
        }
        feedback = build_validation_feedback(errors)
        if feedback:
            response_data['validation_feedback'] = feedback
        return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
    
    @staticmethod
    def server_error_response(message='An unexpected error occurred'):
        return Response({
            'status': 'error',
            'message': message
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Standalone functions for easier imports
def success_response(data=None, message=None, status_code=status.HTTP_200_OK):
    """Return a success response with consistent structure"""
    response_data = {'status': 'success'}
    if message:
        response_data['message'] = message
    if data:
        response_data['data'] = data
    return Response(response_data, status=status_code)


def error_response(message, errors=None, code=None, status_code=status.HTTP_400_BAD_REQUEST):
    """Return an error response with consistent structure"""
    response_data = {
        'status': 'error',
        'message': message
    }
    if code:
        response_data['code'] = code
    if errors:
        response_data['errors'] = errors
        feedback = build_validation_feedback(errors)
        if feedback:
            response_data['validation_feedback'] = feedback
    return Response(response_data, status=status_code)
