from .customer_views import (
    LoanProductListView,
    LoanProductDetailView,
    PreQualifyView,
    LoanApplyView,
    MyApplicationsView,
    ApplicationDetailView,
    RepaymentScheduleView,
    PaymentHistoryView
)
from .admin_views import (
    AdminProductListView,
    AdminProductDetailView,
    AssignApplicationView,
    OfficerWorkloadView
)
from .officer_views import (
    OfficerApplicationListView,
    OfficerApplicationDetailView,
    OfficerReviewView,
    DisburseView,
    RecordPaymentView
)