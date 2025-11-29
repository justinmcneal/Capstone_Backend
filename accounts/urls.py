from django.urls import path
from accounts.views import SignUpView, VerifyOTP, ResendOTP, ForgotPasswordView, VerifyResetOTPView, ResetPasswordView, ChangePasswordView      
from accounts.views.auth_views import LoginView, LogoutView, RefreshTokenView


app_name = 'accounts'

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('verify-email/', VerifyOTP.as_view(), name='verify-email'),
    path('resend-otp/', ResendOTP.as_view(), name='resend-otp'),
    path('refresh-token/', RefreshTokenView.as_view(), name='refresh-token'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login/', LoginView.as_view(), name='login'),

    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-reset-otp/', VerifyResetOTPView.as_view(), name='verify-reset-otp'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password')
]
