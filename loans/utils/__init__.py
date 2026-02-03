"""
Loans Utilities Package
"""
from .reference_generator import (
    generate_payment_reference,
    generate_disbursement_reference,
    generate_application_reference,
)

__all__ = [
    'generate_payment_reference',
    'generate_disbursement_reference',
    'generate_application_reference',
]
