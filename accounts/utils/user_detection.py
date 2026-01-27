"""
User Detection Utility for Unified Authentication Views.

Provides a helper function to detect the authenticated user type
(Customer or LoanOfficer) from the JWT token and return the appropriate model.
"""
from accounts.services.auth_service import AuthService
from accounts.models import LoanOfficer
from bson import ObjectId
import logging

logger = logging.getLogger('authentication')


def get_authenticated_user(request):
    """
    Get the authenticated user from the request.
    
    Checks the JWT token for 'customer_id' or 'loan_officer_id' and returns
    the corresponding model instance.
    
    Args:
        request: The DRF request object with authenticated user
        
    Returns:
        Tuple of (user, user_type) where:
        - user: Customer or LoanOfficer instance, or None if not found
        - user_type: 'customer', 'loan_officer', or None
    """
    # Check for customer
    customer_id = getattr(request.user, 'customer_id', None) or request.user.get('customer_id')
    if customer_id:
        customer = AuthService.get_customer_by_id(customer_id)
        if customer:
            return (customer, 'customer')
    
    # Check for loan officer
    loan_officer_id = getattr(request.user, 'loan_officer_id', None) or request.user.get('loan_officer_id')
    if loan_officer_id:
        try:
            officer = LoanOfficer.find_one({'_id': ObjectId(loan_officer_id)})
            if officer:
                return (officer, 'loan_officer')
        except Exception as e:
            logger.error(f"Error fetching loan officer: {str(e)}")
    
    return (None, None)
