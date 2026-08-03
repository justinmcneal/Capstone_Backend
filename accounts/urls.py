from django.urls import path

from accounts.views import (
    ChangePasswordView,
    ConsentAuditView,
    ConsentHistoryView,
    ConsentView,
    CSRFTokenView,
    ForgotPasswordView,
    ResendOTP,
    ResetPasswordView,
    SignUpView,
    VerifyOTP,
    VerifyResetOTPView,
)
from accounts.views.activity_views import ActiveSessionsView, LoginActivityView
from accounts.views.admin_views import (
    AdminDetailView,
    AdminLoginView,
    AdminLogoutView,
    # Admin Management (Super Admin Only)
    AdminManagementView,
    AdminPermissionsView,
    AdminProfileView,
    LoanOfficerDetailView,
    LoanOfficerManagementView,
)
from accounts.views.auth_views import (
    LoginView,
    LogoutView,
    RefreshTokenView,
    UpdateLanguageView,
)
from accounts.views.contact_views import ContactSupportView
from accounts.views.customer_admin_views import (
    CustomerDeletionFinalizeView,
    CustomerDetailView,
    CustomerManagementView,
    CustomerUnlockView,
    TwoFactorRecoveryAdminView,
)
from accounts.views.account_lifecycle_views import (
    AccountDeletionCancelView,
    AccountDeletionRequestView,
    AccountExportView,
    EmailChangeConfirmView,
    EmailChangeRequestView,
    TwoFactorRecoveryRequestView,
    TwoFactorRecoveryVerifyView,
)
from accounts.views.loan_officer_views import (
    LoanOfficerLoginView,
    LoanOfficerLogoutView,
    LoanOfficerProfileView,
)
from accounts.views.two_factor_views import (
    Confirm2FASetupView,
    Disable2FAView,
    Get2FAStatusView,
    RegenerateBackupCodesView,
    Setup2FAView,
    Verify2FAView,
)

app_name = "accounts"

urlpatterns = [
    # Customer Authentication
    path("csrf-token/", CSRFTokenView.as_view(), name="csrf-token"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("verify-email/", VerifyOTP.as_view(), name="verify-email"),
    path("resend-otp/", ResendOTP.as_view(), name="resend-otp"),
    path("refresh-token/", RefreshTokenView.as_view(), name="refresh-token"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("login/", LoginView.as_view(), name="login"),
    # Password Management (Unified - works for Customer and LoanOfficer)
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("verify-reset-otp/", VerifyResetOTPView.as_view(), name="verify-reset-otp"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    # Two-Factor Authentication (Unified - works for Customer and LoanOfficer)
    path("2fa/setup/", Setup2FAView.as_view(), name="2fa-setup"),
    path("2fa/confirm/", Confirm2FASetupView.as_view(), name="2fa-confirm"),
    path("2fa/verify/", Verify2FAView.as_view(), name="2fa-verify"),
    path("2fa/disable/", Disable2FAView.as_view(), name="2fa-disable"),
    path(
        "2fa/backup-codes/",
        RegenerateBackupCodesView.as_view(),
        name="2fa-backup-codes",
    ),
    path("2fa/status/", Get2FAStatusView.as_view(), name="2fa-status"),
    # Consent Management
    path("consent/", ConsentView.as_view(), name="consent"),
    path("consent/history/", ConsentHistoryView.as_view(), name="consent-history"),
    path("consent/audit/", ConsentAuditView.as_view(), name="consent-audit"),
    path("language/", UpdateLanguageView.as_view(), name="update-language"),
    # Activity & Session Management
    path("sessions/", ActiveSessionsView.as_view(), name="active-sessions"),
    path("login-activity/", LoginActivityView.as_view(), name="login-activity"),
    # Account Lifecycle and Recovery
    path("email-change/request/", EmailChangeRequestView.as_view(), name="email-change-request"),
    path("email-change/confirm/", EmailChangeConfirmView.as_view(), name="email-change-confirm"),
    path("account/export/", AccountExportView.as_view(), name="account-export"),
    path(
        "account/deletion-request/",
        AccountDeletionRequestView.as_view(),
        name="account-deletion-request",
    ),
    path(
        "account/deletion-cancel/",
        AccountDeletionCancelView.as_view(),
        name="account-deletion-cancel",
    ),
    path(
        "2fa/recovery/request/",
        TwoFactorRecoveryRequestView.as_view(),
        name="2fa-recovery-request",
    ),
    path(
        "2fa/recovery/verify/",
        TwoFactorRecoveryVerifyView.as_view(),
        name="2fa-recovery-verify",
    ),
    # Loan Officer Authentication
    path(
        "loan-officer/login/", LoanOfficerLoginView.as_view(), name="loan-officer-login"
    ),
    path(
        "loan-officer/logout/",
        LoanOfficerLogoutView.as_view(),
        name="loan-officer-logout",
    ),
    path("loan-officer/me/", LoanOfficerProfileView.as_view(), name="loan-officer-me"),
    # Admin Authentication
    path("admin/login/", AdminLoginView.as_view(), name="admin-login"),
    path("admin/logout/", AdminLogoutView.as_view(), name="admin-logout"),
    path("admin/me/", AdminProfileView.as_view(), name="admin-me"),
    # Admin - Loan Officer Management
    path(
        "admin/loan-officers/",
        LoanOfficerManagementView.as_view(),
        name="admin-loan-officers",
    ),
    path(
        "admin/loan-officers/<str:officer_id>/",
        LoanOfficerDetailView.as_view(),
        name="admin-loan-officer-detail",
    ),
    # Admin - Customer Management (manage_users permission)
    path(
        "admin/customers/",
        CustomerManagementView.as_view(),
        name="admin-customers",
    ),
    path(
        "admin/customers/<str:customer_id>/",
        CustomerDetailView.as_view(),
        name="admin-customer-detail",
    ),
    path(
        "admin/customers/<str:customer_id>/unlock/",
        CustomerUnlockView.as_view(),
        name="admin-customer-unlock",
    ),
    path(
        "admin/customers/<str:customer_id>/deletion/finalize/",
        CustomerDeletionFinalizeView.as_view(),
        name="admin-customer-deletion-finalize",
    ),
    path(
        "admin/customers/2fa-recovery/",
        TwoFactorRecoveryAdminView.as_view(),
        name="admin-customer-2fa-recovery-list",
    ),
    path(
        "admin/customers/<str:customer_id>/2fa-recovery/",
        TwoFactorRecoveryAdminView.as_view(),
        name="admin-customer-2fa-recovery-decision",
    ),
    # Admin - Admin Management (Super Admin Only)
    path("admin/admins/", AdminManagementView.as_view(), name="admin-admins"),
    path(
        "admin/admins/<str:admin_id>/", AdminDetailView.as_view(), name="admin-detail"
    ),
    path(
        "admin/admins/<str:admin_id>/permissions/",
        AdminPermissionsView.as_view(),
        name="admin-permissions",
    ),
    # Support
    path("contact/", ContactSupportView.as_view(), name="contact-support"),
]
