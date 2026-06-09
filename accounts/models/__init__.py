"""
Models package for the accounts app.

This package contains all database models:
- Customer: MSME users (microentrepreneurs)
- LoanOfficer: Bank/microfinance loan processing staff
- Admin: System administrators
- Consent: User consent records for data and AI features
- BlacklistedToken: Revoked JWT tokens
- RefreshTokenEntry: Active refresh token tracking
"""

from accounts.models.customer import Customer
from accounts.models.tokens import BlacklistedToken, RefreshTokenEntry
from accounts.models.consent import Consent
from accounts.models.loan_officer import LoanOfficer
from accounts.models.admin import Admin, ADMIN_PERMISSIONS

__all__ = [
    "Customer",
    "BlacklistedToken",
    "RefreshTokenEntry",
    "Consent",
    "LoanOfficer",
    "Admin",
    "ADMIN_PERMISSIONS",
]
