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

from accounts.models.activity import ActiveSession, LoginActivity
from accounts.models.admin import ADMIN_PERMISSIONS, Admin
from accounts.models.consent import Consent, ConsentEvent
from accounts.models.customer import Customer
from accounts.models.loan_officer import LoanOfficer
from accounts.models.tokens import BlacklistedToken, RefreshTokenEntry

__all__ = [
    "ADMIN_PERMISSIONS",
    "ActiveSession",
    "Admin",
    "BlacklistedToken",
    "Consent",
    "ConsentEvent",
    "Customer",
    "LoanOfficer",
    "LoginActivity",
    "RefreshTokenEntry",
]
