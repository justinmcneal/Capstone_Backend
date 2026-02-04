from django.urls import path
from loans.views import (
    # Customer
    LoanProductListView,
    LoanProductDetailView,
    PreQualifyView,
    LoanApplyView,
    MyApplicationsView,
    ApplicationDetailView,
    RepaymentScheduleView,
    PaymentHistoryView,
    ResubmitApplicationView,
    RejectionFeedbackView,
    # Admin
    AdminProductListView,
    AdminProductDetailView,
    AssignApplicationView,
    OfficerWorkloadView,
    # Officer
    OfficerApplicationListView,
    OfficerApplicationDetailView,
    OfficerReviewView,
    DisburseView,
    RecordPaymentView,
    ActiveLoansView,
    OfficerScheduleView,
    OfficerPaymentHistoryView,
)


app_name = 'loans'

urlpatterns = [
    # Customer endpoints
    path('products/', LoanProductListView.as_view(), name='products'),
    path('products/<str:product_id>/', LoanProductDetailView.as_view(), name='product-detail'),
    path('pre-qualify/', PreQualifyView.as_view(), name='pre-qualify'),
    path('apply/', LoanApplyView.as_view(), name='apply'),
    path('applications/', MyApplicationsView.as_view(), name='my-applications'),
    path('applications/<str:application_id>/', ApplicationDetailView.as_view(), name='application-detail'),
    path('applications/<str:application_id>/schedule/', RepaymentScheduleView.as_view(), name='application-schedule'),
    path('applications/<str:application_id>/payments/', PaymentHistoryView.as_view(), name='application-payments'),
    path('applications/<str:application_id>/resubmit/', ResubmitApplicationView.as_view(), name='application-resubmit'),
    path('applications/<str:application_id>/feedback/', RejectionFeedbackView.as_view(), name='application-feedback'),
    
    # Admin endpoints (product management)
    path('admin/products/', AdminProductListView.as_view(), name='admin-products'),
    path('admin/products/<str:product_id>/', AdminProductDetailView.as_view(), name='admin-product-detail'),
    
    # Admin endpoints (assignment)
    path('admin/applications/<str:application_id>/assign/', AssignApplicationView.as_view(), name='admin-assign'),
    path('admin/officers/workload/', OfficerWorkloadView.as_view(), name='admin-workload'),
    
    # Loan officer endpoints
    path('officer/applications/', OfficerApplicationListView.as_view(), name='officer-applications'),
    path('officer/applications/<str:application_id>/', OfficerApplicationDetailView.as_view(), name='officer-application-detail'),
    path('officer/applications/<str:application_id>/review/', OfficerReviewView.as_view(), name='officer-review'),
    path('officer/applications/<str:application_id>/disburse/', DisburseView.as_view(), name='officer-disburse'),
    path('officer/payments/', RecordPaymentView.as_view(), name='officer-payments'),
    path('officer/active-loans/', ActiveLoansView.as_view(), name='officer-active-loans'),
    path('officer/applications/<str:application_id>/schedule/', OfficerScheduleView.as_view(), name='officer-schedule'),
    path('officer/applications/<str:application_id>/payments/', OfficerPaymentHistoryView.as_view(), name='officer-payment-history'),
]
