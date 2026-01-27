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
    
    The JWT token stores the user ID in 'customer_id' for ALL user types,
    and uses 'role' to distinguish between customer, loan_officer, and admin.
    
    Args:
        request: The DRF request object with authenticated user
        
    Returns:
        Tuple of (user, user_type) where:
        - user: Customer or LoanOfficer instance, or None if not found
        - user_type: 'customer', 'loan_officer', or None
    """
    user = request.user
    
    # Get user ID and role from the authenticated user
    user_id = getattr(user, 'customer_id', None) or (user.get('customer_id') if hasattr(user, 'get') else None)
    role = getattr(user, 'role', 'customer') or (user.get('role', 'customer') if hasattr(user, 'get') else 'customer')
    
    if not user_id:
        logger.warning("No user_id found in request.user")
        return (None, None)
    
    logger.debug(f"Detected user_id={user_id}, role={role}")
    
    # Fetch the appropriate model based on role
    if role == 'loan_officer':
        try:
            officer = LoanOfficer.find_one({'_id': ObjectId(user_id)})
            if officer:
                return (officer, 'loan_officer')
            logger.warning(f"Loan officer not found with id={user_id}")
        except Exception as e:
            logger.error(f"Error fetching loan officer: {str(e)}")
        return (None, None)
    
    elif role == 'customer':
        customer = AuthService.get_customer_by_id(user_id)
        if customer:
            return (customer, 'customer')
        logger.warning(f"Customer not found with id={user_id}")
        return (None, None)
    
    elif role == 'admin':
        # Admins don't use these endpoints but handle gracefully
        logger.info(f"Admin attempted to access customer/loan_officer endpoint")
        return (None, None)
    
    logger.warning(f"Unknown role: {role}")
    return (None, None)
