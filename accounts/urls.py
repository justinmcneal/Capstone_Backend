from django.urls import path
from accounts.views import SignUpView, VerifyOTP, ResendOTP, ForgotPasswordView, VerifyResetOTPView, ResetPasswordView, ChangePasswordView, ConsentView
from accounts.views.auth_views import LoginView, LogoutView, RefreshTokenView
from accounts.views.two_factor_views import (
    Setup2FAView, 
    Confirm2FASetupView, 
    Verify2FAView, 
    Disable2FAView, 
    RegenerateBackupCodesView,
    Get2FAStatusView
)
from accounts.views.loan_officer_views import LoanOfficerLoginView, LoanOfficerLogoutView
from accounts.views.admin_views import (
    AdminLoginView,
    AdminLogoutView,
    LoanOfficerManagementView,
    LoanOfficerDetailView,
    # Admin Management (Super Admin Only)
    AdminManagementView,
    AdminDetailView,
    AdminPermissionsView
)


app_name = 'accounts'

urlpatterns = [
    # Customer Authentication
    path('signup/', SignUpView.as_view(), name='signup'),
    path('verify-email/', VerifyOTP.as_view(), name='verify-email'),
    path('resend-otp/', ResendOTP.as_view(), name='resend-otp'),
    path('refresh-token/', RefreshTokenView.as_view(), name='refresh-token'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login/', LoginView.as_view(), name='login'),

    # Password Management
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-reset-otp/', VerifyResetOTPView.as_view(), name='verify-reset-otp'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),

    # Two-Factor Authentication (2FA)
    path('2fa/setup/', Setup2FAView.as_view(), name='2fa-setup'),
    path('2fa/confirm/', Confirm2FASetupView.as_view(), name='2fa-confirm'),
    path('2fa/verify/', Verify2FAView.as_view(), name='2fa-verify'),
    path('2fa/disable/', Disable2FAView.as_view(), name='2fa-disable'),
    path('2fa/backup-codes/', RegenerateBackupCodesView.as_view(), name='2fa-backup-codes'),
    path('2fa/status/', Get2FAStatusView.as_view(), name='2fa-status'),

    # Consent Management
    path('consent/', ConsentView.as_view(), name='consent'),

    # Loan Officer Authentication
    path('loan-officer/login/', LoanOfficerLoginView.as_view(), name='loan-officer-login'),
    path('loan-officer/logout/', LoanOfficerLogoutView.as_view(), name='loan-officer-logout'),

    # Admin Authentication
    path('admin/login/', AdminLoginView.as_view(), name='admin-login'),
    path('admin/logout/', AdminLogoutView.as_view(), name='admin-logout'),

    # Admin - Loan Officer Management
    path('admin/loan-officers/', LoanOfficerManagementView.as_view(), name='admin-loan-officers'),
    path('admin/loan-officers/<str:officer_id>/', LoanOfficerDetailView.as_view(), name='admin-loan-officer-detail'),

    # Admin - Admin Management (Super Admin Only)
    path('admin/admins/', AdminManagementView.as_view(), name='admin-admins'),
    path('admin/admins/<str:admin_id>/', AdminDetailView.as_view(), name='admin-detail'),
    path('admin/admins/<str:admin_id>/permissions/', AdminPermissionsView.as_view(), name='admin-permissions'),
]

