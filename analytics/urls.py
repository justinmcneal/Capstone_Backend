from django.urls import path
from analytics.views import (
    AdminDashboardView,
    AuditLogsView,
    AuditLogUsersView,
    AuditLogDetailView,
    OfficerDashboardView,
    CustomerDashboardView
)

app_name = 'analytics'

urlpatterns = [
    # Admin dashboard & audit logs
    path('admin/', AdminDashboardView.as_view(), name='admin-dashboard'),
    path('audit-logs/', AuditLogsView.as_view(), name='audit-logs'),
    path('audit-logs/users/', AuditLogUsersView.as_view(), name='audit-log-users'),
    path('audit-logs/<str:log_id>/', AuditLogDetailView.as_view(), name='audit-log-detail'),
    
    # Loan officer dashboard
    path('officer/', OfficerDashboardView.as_view(), name='officer-dashboard'),
    
    # Customer dashboard
    path('customer/', CustomerDashboardView.as_view(), name='customer-dashboard'),
]
