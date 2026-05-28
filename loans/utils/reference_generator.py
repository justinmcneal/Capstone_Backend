"""
Reference Generator Utility

Generates unique reference numbers for payments and disbursements.
Uses MongoDB counters for sequential numbering.
"""

from datetime import datetime
from django.conf import settings


def get_db():
    """Get MongoDB database connection"""
    return settings.MONGODB


def generate_payment_reference() -> str:
    """
    Generate unique payment reference.

    Format: PAY-YYYYMMDD-NNNNNN
    Example: PAY-20260203-001234

    Returns:
        str: Unique payment reference
    """
    db = get_db()

    # Atomically increment counter
    counter = db.counters.find_one_and_update(
        {"_id": "payment_counter"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )

    seq = counter["seq"]
    date_part = datetime.utcnow().strftime("%Y%m%d")

    return f"PAY-{date_part}-{seq:06d}"


def generate_disbursement_reference() -> str:
    """
    Generate unique disbursement/voucher reference.

    Format: DSB-YYYYMMDD-NNNNNN
    Example: DSB-20260203-000123

    Returns:
        str: Unique disbursement reference
    """
    db = get_db()

    # Atomically increment counter
    counter = db.counters.find_one_and_update(
        {"_id": "disbursement_counter"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )

    seq = counter["seq"]
    date_part = datetime.utcnow().strftime("%Y%m%d")

    return f"DSB-{date_part}-{seq:06d}"


def generate_application_reference() -> str:
    """
    Generate unique loan application reference.

    Format: APP-YYYYMMDD-NNNNNN
    Example: APP-20260203-000456

    Returns:
        str: Unique application reference
    """
    db = get_db()

    counter = db.counters.find_one_and_update(
        {"_id": "application_counter"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )

    seq = counter["seq"]
    date_part = datetime.utcnow().strftime("%Y%m%d")

    return f"APP-{date_part}-{seq:06d}"
