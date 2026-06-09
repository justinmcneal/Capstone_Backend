from .tracker import (
    log_action as log_action,
    log_login as log_login,
    log_loan_submitted as log_loan_submitted,
    log_loan_approved as log_loan_approved,
    log_loan_rejected as log_loan_rejected,
    log_document_uploaded as log_document_uploaded,
    log_profile_updated as log_profile_updated,
)

__all__ = [
    "log_action",
    "log_login",
    "log_loan_submitted",
    "log_loan_approved",
    "log_loan_rejected",
    "log_document_uploaded",
    "log_profile_updated",
]
