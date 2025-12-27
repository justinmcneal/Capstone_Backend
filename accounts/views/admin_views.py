from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from datetime import datetime, timedelta
from bson import ObjectId
import secrets
import string

from accounts.models import Admin, LoanOfficer, ADMIN_PERMISSIONS
from accounts.authentication import CustomJWTAuthentication
from accounts.utils.token_utils import TokenUtils
from accounts.utils.response_helpers import success_response, error_response
import logging

logger = logging.getLogger('admin_auth')


def generate_temp_password(length=12):
    """Generate a secure temporary password"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


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
            username = request.data.get('username', '').strip()
            password = request.data.get('password', '')
            
            if not username or not password:
                return error_response(
                    message="Username and password are required",
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
            refresh_token = request.data.get('refresh_token')
            access_token = request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
            
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
        """List all loan officers"""
        try:
            has_perm, result = self.check_admin_permission(request)
            if not has_perm:
                return result
            
            # Get query parameters
            active_only = request.query_params.get('active', 'true').lower() == 'true'
            department = request.query_params.get('department')
            
            query = {}
            if active_only:
                query['active'] = True
            if department:
                query['department'] = department
            
            officers = LoanOfficer.find(query)
            
            officers_data = [{
                'id': o.id,
                'employee_id': o.employee_id,
                'email': o.email,
                'full_name': o.full_name,
                'department': o.department,
                'active': o.active,
                'created_at': o.created_at.isoformat() if o.created_at else None,
                'two_factor_enabled': o.two_factor_enabled
            } for o in officers]
            
            return success_response(
                data={
                    'loan_officers': officers_data,
                    'total': len(officers_data)
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
            
            # Validate required fields
            required_fields = ['employee_id', 'first_name', 'last_name', 'email']
            for field in required_fields:
                if not request.data.get(field):
                    return error_response(
                        message=f"{field} is required",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
            
            email = request.data.get('email', '').lower().strip()
            employee_id = request.data.get('employee_id', '').strip()
            
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
                first_name=request.data.get('first_name', '').strip(),
                last_name=request.data.get('last_name', '').strip(),
                email=email,
                phone=request.data.get('phone', ''),
                department=request.data.get('department', ''),
                created_by=ObjectId(admin.id),
                must_change_password=True
            )
            officer.set_password(temp_password)
            officer.save()
            
            logger.info(f"Loan officer created: {email} by admin {admin.username}")
            
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
            
            officer = LoanOfficer.find_one({'_id': ObjectId(officer_id)})
            
            if not officer:
                return error_response(
                    message="Loan officer not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Update allowed fields
            allowed_fields = ['first_name', 'last_name', 'phone', 'department', 'active']
            for field in allowed_fields:
                if field in request.data:
                    setattr(officer, field, request.data[field])
            
            officer.save()
            
            return success_response(
                data={
                    'id': officer.id,
                    'email': officer.email,
                    'full_name': officer.full_name,
                    'department': officer.department,
                    'active': officer.active
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
