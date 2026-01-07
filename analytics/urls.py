from django.urls import path
from analytics.views import (
    AdminDashboardView,
    AuditLogsView,
    OfficerDashboardView,
    CustomerDashboardView
)

app_name = 'analytics'

urlpatterns = [
    # Admin dashboard & audit logs
    path('admin/', AdminDashboardView.as_view(), name='admin-dashboard'),
    path('audit-logs/', AuditLogsView.as_view(), name='audit-logs'),
    
    # Loan officer dashboard
    path('officer/', OfficerDashboardView.as_view(), name='officer-dashboard'),
    
    # Customer dashboard
    path('customer/', CustomerDashboardView.as_view(), name='customer-dashboard'),
]
