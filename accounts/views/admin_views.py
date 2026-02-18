from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from django.utils.dateparse import parse_datetime
import secrets
import string

from accounts.models import Admin, LoanOfficer, ADMIN_PERMISSIONS
from accounts.authentication import CustomJWTAuthentication
from accounts.utils.token_utils import TokenUtils
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.email_utils import EmailUtils
from accounts.utils.validation_utils import (
    validate_employee_id,
    validate_person_name,
    normalize_text,
    sanitize_text,
    parse_bool,
    parse_optional_bool,
)
from analytics.models import AuditLog
import logging

logger = logging.getLogger('admin_auth')


def generate_temp_password(length=12):
    """Generate a secure temporary password"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _normalize_datetime(dt):
    """Normalize datetime for safe equality checks (naive UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _validate_last_known_updated_at(raw_value):
    """
    Validate optimistic concurrency timestamp from request.
    Returns (parsed_datetime, error_response_or_none)
    """
    if not raw_value:
        return None, None

    parsed = parse_datetime(str(raw_value))
    if parsed is None:
        return None, error_response(
            message="Invalid last_known_updated_at format",
            errors={'last_known_updated_at': 'Use ISO-8601 datetime string'},
            status_code=status.HTTP_400_BAD_REQUEST
        )
    return parsed, None


def _build_stale_update_response(current_updated_at):
    return error_response(
        message="Record was updated by another user. Refresh and try again.",
        code="stale_update",
        errors={
            'last_known_updated_at': 'Stale record version',
            'current_updated_at': (
                current_updated_at.isoformat() if current_updated_at else None
            ),
        },
        status_code=status.HTTP_409_CONFLICT
    )


class AdminLoginView(APIView):
    """
    Login endpoint for system administrators.
    
    POST /api/auth/admin/login/
    {
        "username": "admin",
        "password": "password123"
    }
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            raw_username = request.data.get('username', '')
            password = request.data.get('password', '')
            if not isinstance(raw_username, str):
                return error_response(
                    message="username must be a string",
                    errors={'username': 'username must be a string'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if not isinstance(password, str):
                return error_response(
                    message="password must be a string",
                    errors={'password': 'password must be a string'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            username = normalize_text(raw_username)
            
            if not username or not password:
                errors = {}
                if not username:
                    errors['username'] = 'Username is required'
                if not password:
                    errors['password'] = 'Password is required'
                return error_response(
                    message="Username and password are required",
                    errors=errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Find admin by username or email
            admin = Admin.find_one({'username': username})
            if not admin:
                admin = Admin.find_one({'email': username.lower()})
            
            if not admin:
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if account is active
            if not admin.active:
                return error_response(
                    message="Account has been deactivated",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Check lockout
            if admin.locked_until and admin.locked_until > datetime.utcnow():
                remaining = (admin.locked_until - datetime.utcnow()).seconds // 60
                return error_response(
                    message=f"Account is locked. Try again in {remaining} minutes.",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Verify password
            if not admin.check_password(password):
                admin.failed_login_attempts += 1
                
                if admin.failed_login_attempts >= 5:
                    admin.locked_until = datetime.utcnow() + timedelta(minutes=30)
                    admin.save()
                    return error_response(
                        message="Account locked due to too many failed attempts. Try again in 30 minutes.",
                        status_code=status.HTTP_403_FORBIDDEN
                    )
                
                admin.save()
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Reset failed attempts
            admin.failed_login_attempts = 0
            admin.locked_until = None
            admin.last_login_attempt = datetime.utcnow()
            admin.save()
            
            # Check if 2FA is enabled
            if admin.two_factor_enabled:
                temp_token = TokenUtils.generate_2fa_temp_token(
                    user_id=admin.id,
                    email=admin.email,
                    role='admin'
                )
                return success_response(
                    data={
                        'requires_2fa': True,
                        'temp_token': temp_token
                    },
                    message="2FA verification required"
                )
            
            # Generate tokens
            tokens = TokenUtils.generate_tokens(
                user_id=admin.id,
                email=admin.email,
                verified=True,
                role='admin',
                refresh_token_days=1  # Shorter session for admins
            )
            
            # Audit log for admin login
            AuditLog.log_action(
                action='user_login',
                user_id=admin.id,
                user_type='admin' if not admin.super_admin else 'super_admin',
                user_email=admin.email,
                description=f'Admin {admin.username} logged in',
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            return success_response(
                data={
                    'access_token': tokens['access'],
                    'refresh_token': tokens['refresh'],
                    'user': {
                        'id': admin.id,
                        'username': admin.username,
                        'email': admin.email,
                        'full_name': admin.full_name,
                        'role': 'admin',
                        'permissions': admin.permissions if not admin.super_admin else ['*'],
                        'super_admin': admin.super_admin
                    }
                },
                message="Login successful"
            )
            
        except Exception as e:
            logger.error(f"Admin login error: {str(e)}")
            return error_response(
                message="An error occurred during login",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminLogoutView(APIView):
    """
    Logout endpoint for administrators.
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            refresh_token = str(request.data.get('refresh_token') or '').strip()
            access_token = request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '').strip()
            
            if refresh_token:
                TokenUtils.blacklist_token(refresh_token, token_type='refresh')
            
            if access_token:
                TokenUtils.blacklist_token(access_token, token_type='access')
            
            return success_response(message="Logged out successfully")
            
        except Exception as e:
            logger.error(f"Admin logout error: {str(e)}")
            return success_response(message="Logged out successfully")


class AdminRequiredMixin:
    """Mixin to require admin authentication and permissions"""
    required_permissions = []
    
    def check_admin_permission(self, request):
        """Check if authenticated user is admin with required permissions"""
        user = request.user
        
        if not hasattr(user, 'role') or user.role != 'admin':
            return False, error_response(
                message="Admin access required",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        # Get admin from database to check permissions
        admin = Admin.find_one({'_id': ObjectId(user.customer_id)})
        
        if not admin:
            return False, error_response(
                message="Admin not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if not admin.active:
            return False, error_response(
                message="Admin account is deactivated",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        # Check permissions
        if self.required_permissions:
            if not admin.has_all_permissions(self.required_permissions):
                return False, error_response(
                    message="Insufficient permissions",
                    status_code=status.HTTP_403_FORBIDDEN
                )
        
        return True, admin


class LoanOfficerManagementView(AdminRequiredMixin, APIView):
    """
    Admin endpoints for managing loan officers.
    
    GET /api/auth/admin/loan-officers/ - List all loan officers
    POST /api/auth/admin/loan-officers/ - Create new loan officer
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ['create_loan_officer']
    
    def get(self, request):
        """List all loan officers with search, filtering, and pagination"""
        import re
        try:
            has_perm, result = self.check_admin_permission(request)
            if not has_perm:
                return result
            
            # Get query parameters
            search = sanitize_text(request.query_params.get('search', ''))
            active_raw = request.query_params.get('active')
            department = sanitize_text(request.query_params.get('department', ''))
            try:
                page = int(request.query_params.get('page', 1))
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid page parameter",
                    errors={'page': 'page must be an integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            try:
                page_size = min(int(request.query_params.get('page_size', 20)), 100)
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid page_size parameter",
                    errors={'page_size': 'page_size must be an integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if page < 1:
                return error_response(
                    message="Invalid page parameter",
                    errors={'page': 'page must be at least 1'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if page_size < 1:
                return error_response(
                    message="Invalid page_size parameter",
                    errors={'page_size': 'page_size must be at least 1'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            sort_by = sanitize_text(request.query_params.get('sort_by', 'created_at'))
            sort_order = sanitize_text(request.query_params.get('sort_order', 'desc')).lower()
            if sort_order not in {'asc', 'desc'}:
                return error_response(
                    message="Invalid sort_order parameter",
                    errors={'sort_order': 'sort_order must be asc or desc'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            query = {}
            
            # Active filter - only apply if explicitly provided
            active_param = None
            if active_raw is not None:
                active_text = sanitize_text(active_raw).lower()
                if active_text != 'all':
                    active_valid, active_param, active_error = parse_optional_bool(active_raw, 'active')
                    if not active_valid:
                        return error_response(
                            message="Invalid active filter",
                            errors={'active': active_error},
                            status_code=status.HTTP_400_BAD_REQUEST
                        )
            if active_param is not None:
                query['active'] = active_param
            
            if department:
                query['department'] = department
            
            # Search filter - search in name, email, employee_id
            if search:
                search_regex = re.compile(re.escape(search), re.IGNORECASE)
                query['$or'] = [
                    {'first_name': {'$regex': search_regex}},
                    {'last_name': {'$regex': search_regex}},
                    {'email': {'$regex': search_regex}},
                    {'employee_id': {'$regex': search_regex}},
                ]
            
            # Get total count before pagination
            all_officers = list(LoanOfficer.find(query))
            total = len(all_officers)
            
            # Sort
            sort_direction = -1 if sort_order == 'desc' else 1
            valid_sort_fields = ['created_at', 'full_name', 'email', 'employee_id', 'department']
            if sort_by not in valid_sort_fields:
                sort_by = 'created_at'
            
            # Sort in Python since LoanOfficer.find returns list
            if sort_by == 'full_name':
                all_officers.sort(key=lambda o: o.full_name.lower(), reverse=(sort_order == 'desc'))
            elif sort_by == 'email':
                all_officers.sort(key=lambda o: o.email.lower(), reverse=(sort_order == 'desc'))
            elif sort_by == 'employee_id':
                all_officers.sort(key=lambda o: o.employee_id.lower(), reverse=(sort_order == 'desc'))
            elif sort_by == 'department':
                all_officers.sort(key=lambda o: (o.department or '').lower(), reverse=(sort_order == 'desc'))
            else:  # created_at
                all_officers.sort(key=lambda o: o.created_at or datetime.min, reverse=(sort_order == 'desc'))
            
            # Paginate
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_officers = all_officers[start_idx:end_idx]
            
            officers_data = [{
                'id': o.id,
                'employee_id': o.employee_id,
                'email': o.email,
                'full_name': o.full_name,
                'department': o.department,
                'active': o.active,
                'created_at': o.created_at.isoformat() if o.created_at else None,
                'two_factor_enabled': o.two_factor_enabled
            } for o in paginated_officers]
            
            return success_response(
                data={
                    'loan_officers': officers_data,
                    'total': total,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': (total + page_size - 1) // page_size if total > 0 else 1
                },
                message="Loan officers retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"List loan officers error: {str(e)}")
            return error_response(
                message="Failed to retrieve loan officers",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Create a new loan officer (admin only)"""
        try:
            has_perm, result = self.check_admin_permission(request)
            if not has_perm:
                return result
            
            admin = result  # result is the admin object when has_perm is True
            
            employee_id_valid, employee_id_error, employee_id = validate_employee_id(
                request.data.get('employee_id', ''),
                field_name='Employee ID',
                max_length=50
            )
            first_name = request.data.get('first_name', '')
            last_name = request.data.get('last_name', '')
            email = EmailUtils.normalize_email(str(request.data.get('email') or ''))

            # Validate required fields
            missing_errors = {}
            if not normalize_text(first_name):
                missing_errors['first_name'] = "First Name is required"
            if not normalize_text(last_name):
                missing_errors['last_name'] = "Last Name is required"
            if not email:
                missing_errors['email'] = "Email is required"
            if missing_errors:
                return error_response(
                    message="Validation failed",
                    errors=missing_errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            if not employee_id_valid:
                return error_response(
                    message=employee_id_error,
                    errors={'employee_id': employee_id_error},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            first_name_valid, first_name_error, first_name_normalized = validate_person_name(
                first_name,
                field_name='First name',
                max_length=50
            )
            if not first_name_valid:
                return error_response(
                    message=first_name_error,
                    errors={'first_name': first_name_error},
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            last_name_valid, last_name_error, last_name_normalized = validate_person_name(
                last_name,
                field_name='Last name',
                max_length=50
            )
            if not last_name_valid:
                return error_response(
                    message=last_name_error,
                    errors={'last_name': last_name_error},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if email already exists
            if LoanOfficer.find_one({'email': email}):
                return error_response(
                    message="A loan officer with this email already exists",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if employee_id already exists
            if LoanOfficer.find_one({'employee_id': employee_id}):
                return error_response(
                    message="A loan officer with this employee ID already exists",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Generate temporary password
            temp_password = generate_temp_password()
            
            # Create loan officer
            officer = LoanOfficer(
                employee_id=employee_id,
                first_name=first_name_normalized,
                last_name=last_name_normalized,
                email=email,
                phone=sanitize_text(request.data.get('phone', '')),
                department=sanitize_text(request.data.get('department', '')),
                created_by=ObjectId(admin.id),
                must_change_password=True
            )
            officer.set_password(temp_password)
            officer.save()
            
            logger.info(f"Loan officer created: {email} by admin {admin.username}")
            
            # Audit log
            AuditLog.log_action(
                action='admin_action',
                user_id=admin.id,
                user_type='admin' if not admin.super_admin else 'super_admin',
                user_email=admin.email,
                description=f'Created loan officer: {email}',
                resource_type='loan_officer',
                resource_id=officer.id,
                details={'officer_email': email, 'employee_id': employee_id},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            return success_response(
                data={
                    'loan_officer': {
                        'id': officer.id,
                        'employee_id': officer.employee_id,
                        'email': officer.email,
                        'full_name': officer.full_name,
                        'department': officer.department
                    },
                    'temporary_password': temp_password,
                    'message': 'Send this temporary password to the loan officer securely. They will be required to change it on first login.'
                },
                message="Loan officer created successfully",
                status_code=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Create loan officer error: {str(e)}")
            return error_response(
                message="Failed to create loan officer",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LoanOfficerDetailView(AdminRequiredMixin, APIView):
    """
    Admin endpoints for managing a specific loan officer.
    
    GET /api/auth/admin/loan-officers/<id>/ - Get loan officer details
    PUT /api/auth/admin/loan-officers/<id>/ - Update loan officer
    DELETE /api/auth/admin/loan-officers/<id>/ - Deactivate loan officer
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    required_permissions = ['manage_loan_officers']
    
    def get(self, request, officer_id):
        """Get loan officer details"""
        try:
            has_perm, result = self.check_admin_permission(request)
            if not has_perm:
                return result
            
            officer = LoanOfficer.find_one({'_id': ObjectId(officer_id)})
            
            if not officer:
                return error_response(
                    message="Loan officer not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            return success_response(
                data={
                    'id': officer.id,
                    'employee_id': officer.employee_id,
                    'email': officer.email,
                    'first_name': officer.first_name,
                    'last_name': officer.last_name,
                    'full_name': officer.full_name,
                    'phone': officer.phone,
                    'department': officer.department,
                    'active': officer.active,
                    'verified': officer.verified,
                    'two_factor_enabled': officer.two_factor_enabled,
                    'created_at': officer.created_at.isoformat() if officer.created_at else None,
                    'updated_at': officer.updated_at.isoformat() if officer.updated_at else None,
                    'must_change_password': officer.must_change_password
                },
                message="Loan officer retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"Get loan officer error: {str(e)}")
            return error_response(
                message="Failed to retrieve loan officer",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def put(self, request, officer_id):
        """Update loan officer details"""
        try:
            has_perm, result = self.check_admin_permission(request)
            if not has_perm:
                return result
            
            admin = result  # get the admin from check_admin_permission
            
            officer = LoanOfficer.find_one({'_id': ObjectId(officer_id)})
            
            if not officer:
                return error_response(
                    message="Loan officer not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            client_updated_at_raw = request.data.get('last_known_updated_at')
            client_updated_at, version_error = _validate_last_known_updated_at(client_updated_at_raw)
            if version_error:
                return version_error
            if (
                client_updated_at is not None and
                _normalize_datetime(client_updated_at) != _normalize_datetime(officer.updated_at)
            ):
                return _build_stale_update_response(officer.updated_at)
            
            # Track changes for audit log
            changes = {}
            
            # Update allowed fields
            allowed_fields = ['first_name', 'last_name', 'phone', 'department', 'active']
            for field in allowed_fields:
                if field in request.data:
                    old_value = getattr(officer, field)
                    new_value = request.data[field]

                    if field in ['first_name', 'last_name']:
                        is_valid, error_msg, normalized_name = validate_person_name(
                            new_value,
                            field_name='First name' if field == 'first_name' else 'Last name',
                            max_length=50
                        )
                        if not is_valid:
                            return error_response(
                                message=error_msg,
                                errors={field: error_msg},
                                status_code=status.HTTP_400_BAD_REQUEST
                            )
                        new_value = normalized_name
                    elif field == 'active':
                        is_valid, parsed_active, parse_error = parse_bool(new_value, 'active')
                        if not is_valid:
                            return error_response(
                                message="Invalid active value",
                                errors={'active': parse_error},
                                status_code=status.HTTP_400_BAD_REQUEST
                            )
                        new_value = parsed_active
                    elif isinstance(new_value, str):
                        new_value = sanitize_text(new_value)
                    elif field in ['phone', 'department'] and new_value is not None:
                        return error_response(
                            message=f"{field} must be a string",
                            errors={field: f"{field} must be a string"},
                            status_code=status.HTTP_400_BAD_REQUEST
                        )

                    if old_value != new_value:
                        changes[field] = {'old': old_value, 'new': new_value}
                    setattr(officer, field, new_value)
            
            officer.save()
            
            logger.info(f"Loan officer updated: {officer.email} by admin {admin.username}")
            
            # Audit log
            if changes:
                AuditLog.log_action(
                    action='admin_action',
                    user_id=admin.id,
                    user_type='admin' if not admin.super_admin else 'super_admin',
                    user_email=admin.email,
                    description=f'Updated loan officer: {officer.email}',
                    resource_type='loan_officer',
                    resource_id=officer.id,
                    details={'officer_email': officer.email, 'changes': changes},
                    ip_address=request.META.get('REMOTE_ADDR', '')
                )
            
            return success_response(
                data={
                    'id': officer.id,
                    'email': officer.email,
                    'full_name': officer.full_name,
                    'department': officer.department,
                    'active': officer.active,
                    'updated_at': officer.updated_at.isoformat() if officer.updated_at else None
                },
                message="Loan officer updated successfully"
            )
            
        except Exception as e:
            logger.error(f"Update loan officer error: {str(e)}")
            return error_response(
                message="Failed to update loan officer",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, officer_id):
        """Deactivate loan officer (soft delete)"""
        try:
            has_perm, result = self.check_admin_permission(request)
            if not has_perm:
                return result
            
            officer = LoanOfficer.find_one({'_id': ObjectId(officer_id)})
            
            if not officer:
                return error_response(
                    message="Loan officer not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Soft delete - just deactivate
            officer.active = False
            officer.save()
            
            logger.info(f"Loan officer deactivated: {officer.email}")
            
            return success_response(
                message="Loan officer deactivated successfully"
            )
            
        except Exception as e:
            logger.error(f"Deactivate loan officer error: {str(e)}")
            return error_response(
                message="Failed to deactivate loan officer",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# =============================================================================
# ADMIN MANAGEMENT (Super Admin Only)
# =============================================================================

class SuperAdminRequiredMixin:
    """Mixin to require super admin access"""
    
    def check_super_admin(self, request):
        """Check if authenticated user is a super admin"""
        user = request.user
        
        if not hasattr(user, 'role') or user.role != 'admin':
            return False, error_response(
                message="Admin access required",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        admin = Admin.find_one({'_id': ObjectId(user.customer_id)})
        
        if not admin:
            return False, error_response(
                message="Admin not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        if not admin.active:
            return False, error_response(
                message="Admin account is deactivated",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        if not admin.super_admin:
            return False, error_response(
                message="Super admin access required",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        return True, admin


class AdminManagementView(SuperAdminRequiredMixin, APIView):
    """
    Super Admin endpoints for managing other admins.
    
    GET /api/auth/admin/admins/ - List all admins
    POST /api/auth/admin/admins/ - Create new admin
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List all admins with search, filtering, and pagination"""
        import re
        try:
            has_perm, result = self.check_super_admin(request)
            if not has_perm:
                return result
            
            current_admin = result
            
            # Get query parameters
            search = sanitize_text(request.query_params.get('search', ''))
            active_raw = request.query_params.get('active')
            try:
                page = int(request.query_params.get('page', 1))
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid page parameter",
                    errors={'page': 'page must be an integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            try:
                page_size = min(int(request.query_params.get('page_size', 20)), 100)
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid page_size parameter",
                    errors={'page_size': 'page_size must be an integer'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if page < 1:
                return error_response(
                    message="Invalid page parameter",
                    errors={'page': 'page must be at least 1'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if page_size < 1:
                return error_response(
                    message="Invalid page_size parameter",
                    errors={'page_size': 'page_size must be at least 1'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            sort_by = sanitize_text(request.query_params.get('sort_by', 'created_at'))
            sort_order = sanitize_text(request.query_params.get('sort_order', 'desc')).lower()
            if sort_order not in {'asc', 'desc'}:
                return error_response(
                    message="Invalid sort_order parameter",
                    errors={'sort_order': 'sort_order must be asc or desc'},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            query = {}
            
            # Active filter - only apply if explicitly provided
            active_param = None
            if active_raw is not None:
                active_text = sanitize_text(active_raw).lower()
                if active_text != 'all':
                    active_valid, active_param, active_error = parse_optional_bool(active_raw, 'active')
                    if not active_valid:
                        return error_response(
                            message="Invalid active filter",
                            errors={'active': active_error},
                            status_code=status.HTTP_400_BAD_REQUEST
                        )
            if active_param is not None:
                query['active'] = active_param
            
            # Search filter - search in username, name, email
            if search:
                search_regex = re.compile(re.escape(search), re.IGNORECASE)
                query['$or'] = [
                    {'username': {'$regex': search_regex}},
                    {'first_name': {'$regex': search_regex}},
                    {'last_name': {'$regex': search_regex}},
                    {'email': {'$regex': search_regex}},
                ]
            
            # Get all matching admins
            all_admins = list(Admin.find(query))
            total = len(all_admins)
            
            # Sort
            valid_sort_fields = ['created_at', 'full_name', 'email', 'username']
            if sort_by not in valid_sort_fields:
                sort_by = 'created_at'
            
            if sort_by == 'full_name':
                all_admins.sort(key=lambda a: a.full_name.lower(), reverse=(sort_order == 'desc'))
            elif sort_by == 'email':
                all_admins.sort(key=lambda a: a.email.lower(), reverse=(sort_order == 'desc'))
            elif sort_by == 'username':
                all_admins.sort(key=lambda a: a.username.lower(), reverse=(sort_order == 'desc'))
            else:  # created_at
                all_admins.sort(key=lambda a: a.created_at or datetime.min, reverse=(sort_order == 'desc'))
            
            # Paginate
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_admins = all_admins[start_idx:end_idx]
            
            admins_data = [{
                'id': a.id,
                'username': a.username,
                'email': a.email,
                'full_name': a.full_name,
                'super_admin': a.super_admin,
                'permissions': a.permissions if not a.super_admin else ['*'],
                'active': a.active,
                'two_factor_enabled': a.two_factor_enabled,
                'created_at': a.created_at.isoformat() if a.created_at else None
            } for a in paginated_admins]
            
            return success_response(
                data={
                    'admins': admins_data,
                    'total': total,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': (total + page_size - 1) // page_size if total > 0 else 1
                },
                message="Admins retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"List admins error: {str(e)}")
            return error_response(
                message="Failed to retrieve admins",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Create a new admin (super admin only)"""
        from accounts.serializers.admin_serializers import AdminCreateSerializer
        
        try:
            has_perm, result = self.check_super_admin(request)
            if not has_perm:
                return result
            
            current_admin = result
            
            serializer = AdminCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid admin data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            username = data['username'].strip()
            email = data['email'].lower().strip()
            
            # Check if username already exists
            if Admin.find_one({'username': username}):
                return error_response(
                    message="An admin with this username already exists",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if email already exists
            if Admin.find_one({'email': email}):
                return error_response(
                    message="An admin with this email already exists",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Generate temporary password
            temp_password = generate_temp_password()
            
            # Create admin
            new_admin = Admin(
                username=username,
                email=email,
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
                super_admin=data.get('super_admin', False),
                permissions=data.get('permissions', []) if not data.get('super_admin') else ['*']
            )
            new_admin.set_password(temp_password)
            new_admin.save()
            
            logger.info(f"Admin created: {username} by super admin {current_admin.username}")
            
            return success_response(
                data={
                    'admin': {
                        'id': new_admin.id,
                        'username': new_admin.username,
                        'email': new_admin.email,
                        'full_name': new_admin.full_name,
                        'super_admin': new_admin.super_admin,
                        'permissions': new_admin.permissions
                    },
                    'temporary_password': temp_password,
                    'message': 'Send this temporary password to the admin securely.'
                },
                message="Admin created successfully",
                status_code=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Create admin error: {str(e)}")
            return error_response(
                message="Failed to create admin",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminDetailView(SuperAdminRequiredMixin, APIView):
    """
    Super Admin endpoints for managing a specific admin.
    
    GET /api/auth/admin/admins/<id>/ - Get admin details
    PUT /api/auth/admin/admins/<id>/ - Update admin
    DELETE /api/auth/admin/admins/<id>/ - Deactivate admin
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, admin_id):
        """Get admin details"""
        try:
            has_perm, result = self.check_super_admin(request)
            if not has_perm:
                return result
            
            target_admin = Admin.find_one({'_id': ObjectId(admin_id)})
            
            if not target_admin:
                return error_response(
                    message="Admin not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            return success_response(
                data={
                    'id': target_admin.id,
                    'username': target_admin.username,
                    'email': target_admin.email,
                    'first_name': target_admin.first_name,
                    'last_name': target_admin.last_name,
                    'full_name': target_admin.full_name,
                    'super_admin': target_admin.super_admin,
                    'permissions': target_admin.permissions if not target_admin.super_admin else ['*'],
                    'active': target_admin.active,
                    'two_factor_enabled': target_admin.two_factor_enabled,
                    'created_at': target_admin.created_at.isoformat() if target_admin.created_at else None,
                    'updated_at': target_admin.updated_at.isoformat() if target_admin.updated_at else None
                },
                message="Admin retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"Get admin error: {str(e)}")
            return error_response(
                message="Failed to retrieve admin",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def put(self, request, admin_id):
        """Update admin details"""
        from accounts.serializers.admin_serializers import AdminUpdateSerializer
        
        try:
            has_perm, result = self.check_super_admin(request)
            if not has_perm:
                return result
            
            current_admin = result
            
            target_admin = Admin.find_one({'_id': ObjectId(admin_id)})
            
            if not target_admin:
                return error_response(
                    message="Admin not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            client_updated_at_raw = request.data.get('last_known_updated_at')
            client_updated_at, version_error = _validate_last_known_updated_at(client_updated_at_raw)
            if version_error:
                return version_error
            if (
                client_updated_at is not None and
                _normalize_datetime(client_updated_at) != _normalize_datetime(target_admin.updated_at)
            ):
                return _build_stale_update_response(target_admin.updated_at)
            
            # Prevent self-deactivation
            if str(current_admin.id) == str(target_admin.id) and request.data.get('active') is False:
                return error_response(
                    message="Cannot deactivate your own account",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            serializer = AdminUpdateSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            
            if 'first_name' in data:
                target_admin.first_name = data['first_name']
            if 'last_name' in data:
                target_admin.last_name = data['last_name']
            if 'active' in data:
                target_admin.active = data['active']
            
            target_admin.save()
            
            logger.info(f"Admin updated: {target_admin.username} by {current_admin.username}")
            
            return success_response(
                data={
                    'id': target_admin.id,
                    'username': target_admin.username,
                    'email': target_admin.email,
                    'full_name': target_admin.full_name,
                    'active': target_admin.active,
                    'updated_at': target_admin.updated_at.isoformat() if target_admin.updated_at else None
                },
                message="Admin updated successfully"
            )
            
        except Exception as e:
            logger.error(f"Update admin error: {str(e)}")
            return error_response(
                message="Failed to update admin",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, admin_id):
        """Deactivate admin (soft delete)"""
        try:
            has_perm, result = self.check_super_admin(request)
            if not has_perm:
                return result
            
            current_admin = result
            
            target_admin = Admin.find_one({'_id': ObjectId(admin_id)})
            
            if not target_admin:
                return error_response(
                    message="Admin not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Prevent self-deactivation
            if str(current_admin.id) == str(target_admin.id):
                return error_response(
                    message="Cannot deactivate your own account",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            target_admin.active = False
            target_admin.save()
            
            logger.info(f"Admin deactivated: {target_admin.username} by {current_admin.username}")
            
            return success_response(message="Admin deactivated successfully")
            
        except Exception as e:
            logger.error(f"Deactivate admin error: {str(e)}")
            return error_response(
                message="Failed to deactivate admin",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminPermissionsView(SuperAdminRequiredMixin, APIView):
    """
    Super Admin endpoint for updating admin permissions.
    
    PUT /api/auth/admin/admins/<id>/permissions/ - Update permissions
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def put(self, request, admin_id):
        """Update admin permissions"""
        from accounts.serializers.admin_serializers import AdminPermissionsSerializer
        
        try:
            has_perm, result = self.check_super_admin(request)
            if not has_perm:
                return result
            
            current_admin = result
            
            target_admin = Admin.find_one({'_id': ObjectId(admin_id)})
            
            if not target_admin:
                return error_response(
                    message="Admin not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            serializer = AdminPermissionsSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid permissions data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            
            # Update super_admin status
            if 'super_admin' in data:
                target_admin.super_admin = data['super_admin']
                if data['super_admin']:
                    target_admin.permissions = ['*']
            
            # Update specific permissions (only if not super_admin)
            if 'permissions' in data and not target_admin.super_admin:
                target_admin.permissions = data['permissions']
            
            target_admin.save()
            
            logger.info(f"Permissions updated for {target_admin.username} by {current_admin.username}")
            
            return success_response(
                data={
                    'id': target_admin.id,
                    'username': target_admin.username,
                    'super_admin': target_admin.super_admin,
                    'permissions': target_admin.permissions if not target_admin.super_admin else ['*']
                },
                message="Permissions updated successfully"
            )
            
        except Exception as e:
            logger.error(f"Update permissions error: {str(e)}")
            return error_response(
                message="Failed to update permissions",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
