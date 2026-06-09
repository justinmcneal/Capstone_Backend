from .admin_dashboard import (
    AdminDashboardView as AdminDashboardView,
    AuditLogsView as AuditLogsView,
    AuditLogUsersView as AuditLogUsersView,
    AuditLogDetailView as AuditLogDetailView,
)
from .officer_dashboard import (
    OfficerDashboardView as OfficerDashboardView,
    OfficerAuditLogsView as OfficerAuditLogsView,
)
from .customer_dashboard import CustomerDashboardView as CustomerDashboardView

__all__ = [
    "AdminDashboardView",
    "AuditLogsView",
    "AuditLogUsersView",
    "AuditLogDetailView",
    "OfficerDashboardView",
    "OfficerAuditLogsView",
    "CustomerDashboardView",
]
