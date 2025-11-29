from django.urls import path
from accounts.views import SignUpView, VerifyOTP, ResendOTP
from accounts.views.auth_views import LoginView, LogoutView, RefreshTokenView

app_name = 'accounts'

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('verify-email/', VerifyOTP.as_view(), name='verify-email'),
    path('resend-otp/', ResendOTP.as_view(), name='resend-otp'),
    path('refresh-token/', RefreshTokenView.as_view(), name='refresh-token'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login/', LoginView.as_view(), name='login'),
]
