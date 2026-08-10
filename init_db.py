"""
Initialize MongoDB database by creating required indexes.
This should be run for production deployments to enforce uniqueness and TTL expectations.

Usage:
    python init_db.py
"""

import os
import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from analytics.models import AuditLog  # noqa: E402
from ai_assistant.models import AIInteraction  # noqa: E402
from accounts.models import (  # noqa: E402
    ActiveSession,
    Admin,
    BlacklistedToken,
    Consent,
    ConsentEvent,
    Customer,
    LoanOfficer,
    LoginActivity,
    RefreshTokenEntry,
)
from documents.models import (  # noqa: E402
    Document,
    DocumentStorageCleanup,
    DocumentUploadSession,
)
from loans.models import (  # noqa: E402
    LoanApplication,
    LoanPayment,
    LoanProduct,
    RepaymentSchedule,
)
from loans.blockchain.models import BlockchainTransaction  # noqa: E402
from notifications.models import Notification  # noqa: E402
from notifications.models.device_token import DeviceToken  # noqa: E402
from pymongo.errors import DuplicateKeyError, OperationFailure  # noqa: E402
from django.conf import settings  # noqa: E402
from profiles.models import (  # noqa: E402
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    RiskReviewRequest,
)


def create_indexes():
    """Create indexes for all models"""
    print("Creating indexes for MongoDB collections...")
    print("-" * 50)

    # Customer indexes
    try:
        print("Creating indexes for Customer collection...")
        Customer.create_indexes()
        print("✓ Customer indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ Customer indexes already exist, skipping")
    except Exception as e:
        print(f"✗ Customer error: {e}")

    # BlacklistedToken indexes
    try:
        print("Creating indexes for BlacklistedToken collection...")

        # Clean duplicates first
        db = settings.MONGODB
        if db is not None:
            collection = db["blacklisted_tokens"]

            # Find and remove duplicates
            pipeline = [
                {
                    "$group": {
                        "_id": "$token",
                        "count": {"$sum": 1},
                        "ids": {"$push": "$_id"},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
            ]
            duplicates = list(collection.aggregate(pipeline))

            for doc in duplicates:
                ids_to_remove = doc["ids"][1:]  # Keep first, remove rest
                collection.delete_many({"_id": {"$in": ids_to_remove}})
                print(f"  → Cleaned {len(ids_to_remove)} duplicate tokens")

        BlacklistedToken.create_indexes()
        print("✓ BlacklistedToken indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ BlacklistedToken indexes already exist, skipping")
    except Exception as e:
        print(f"✗ BlacklistedToken error: {e}")

    # RefreshTokenEntry indexes
    try:
        print("Creating indexes for RefreshTokenEntry collection...")
        RefreshTokenEntry.create_indexes()
        print("✓ RefreshTokenEntry indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ RefreshTokenEntry indexes already exist, skipping")
    except Exception as e:
        print(f"✗ RefreshTokenEntry error: {e}")

    # LoanOfficer indexes
    try:
        print("Creating indexes for LoanOfficer collection...")
        LoanOfficer.create_indexes()
        print("✓ LoanOfficer indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ LoanOfficer indexes already exist, skipping")
    except Exception as e:
        print(f"✗ LoanOfficer error: {e}")

    # Admin indexes
    try:
        print("Creating indexes for Admin collection...")
        Admin.create_indexes()
        print("✓ Admin indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ Admin indexes already exist, skipping")
    except Exception as e:
        print(f"✗ Admin error: {e}")

    # Consent indexes
    try:
        print("Creating indexes for Consent collection...")
        Consent.create_indexes()
        ConsentEvent.create_indexes()
        print("✓ Consent indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ Consent indexes already exist, skipping")
    except Exception as e:
        print(f"✗ Consent error: {e}")

    # Profile indexes
    try:
        print("Creating indexes for CustomerProfile collection...")
        CustomerProfile.create_indexes()
        print("✓ CustomerProfile indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ CustomerProfile indexes already exist, skipping")
    except Exception as e:
        print(f"✗ CustomerProfile error: {e}")

    try:
        print("Creating indexes for BusinessProfile collection...")
        BusinessProfile.create_indexes()
        print("✓ BusinessProfile indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ BusinessProfile indexes already exist, skipping")
    except Exception as e:
        print(f"✗ BusinessProfile error: {e}")

    try:
        print("Creating indexes for AlternativeData collection...")
        AlternativeData.create_indexes()
        print("✓ AlternativeData indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ AlternativeData indexes already exist, skipping")
    except Exception as e:
        print(f"✗ AlternativeData error: {e}")

    try:
        print("Creating indexes for RiskReviewRequest collection...")
        RiskReviewRequest.create_indexes()
        print("✓ RiskReviewRequest indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ RiskReviewRequest indexes already exist, skipping")
    except Exception as e:
        print(f"✗ RiskReviewRequest error: {e}")

    try:
        print("Creating indexes for AuditLog collection...")
        AuditLog.create_indexes()
        print("✓ AuditLog indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ AuditLog indexes already exist, skipping")
    except Exception as e:
        print(f"✗ AuditLog error: {e}")

    try:
        print("Creating indexes for audit failure recovery...")
        settings.MONGODB["audit_write_failures"].create_index(
            [("domain", 1), ("resolved_at", 1), ("occurred_at", 1)]
        )
        print("✓ Audit failure recovery indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ Audit failure recovery indexes already exist, skipping")
    except Exception as e:
        print(f"✗ Audit failure recovery index error: {e}")

    try:
        print("Creating indexes for AIInteraction collection...")
        AIInteraction.create_indexes()
        print("✓ AIInteraction indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ AIInteraction indexes already exist, skipping")
    except Exception as e:
        print(f"✗ AIInteraction error: {e}")

    # Loan indexes
    try:
        print("Creating indexes for LoanApplication collection...")
        LoanApplication.create_indexes()
        print("✓ LoanApplication indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ LoanApplication indexes already exist, skipping")
    except Exception as e:
        print(f"✗ LoanApplication error: {e}")

    try:
        print("Creating indexes for LoanProduct collection...")
        LoanProduct.create_indexes()
        print("✓ LoanProduct indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ LoanProduct indexes already exist, skipping")
    except Exception as e:
        print(f"✗ LoanProduct error: {e}")

    try:
        print("Creating indexes for RepaymentSchedule collection...")
        RepaymentSchedule.create_indexes()
        print("✓ RepaymentSchedule indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ RepaymentSchedule indexes already exist, skipping")
    except Exception as e:
        print(f"✗ RepaymentSchedule error: {e}")

    try:
        print("Creating indexes for LoanPayment collection...")
        LoanPayment.create_indexes()
        print("✓ LoanPayment indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ LoanPayment indexes already exist, skipping")
    except Exception as e:
        print(f"✗ LoanPayment error: {e}")

    try:
        print("Creating indexes for BlockchainTransaction collection...")
        BlockchainTransaction.create_indexes()
        print("✓ BlockchainTransaction indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ BlockchainTransaction indexes already exist, skipping")
    except Exception as e:
        print(f"✗ BlockchainTransaction error: {e}")

    # Document indexes
    try:
        print("Creating indexes for Document collection...")
        Document.create_indexes()
        print("✓ Document indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ Document indexes already exist, skipping")
    except Exception as e:
        print(f"✗ Document error: {e}")

    try:
        print("Creating indexes for DocumentUploadSession collection...")
        DocumentUploadSession.create_indexes()
        print("✓ DocumentUploadSession indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ DocumentUploadSession indexes already exist, skipping")
    except Exception as e:
        print(f"✗ DocumentUploadSession error: {e}")

    try:
        print("Creating indexes for DocumentStorageCleanup collection...")
        DocumentStorageCleanup.create_indexes()
        print("✓ DocumentStorageCleanup indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ DocumentStorageCleanup indexes already exist, skipping")
    except Exception as e:
        print(f"✗ DocumentStorageCleanup error: {e}")

    # Notification indexes
    try:
        print("Creating indexes for Notification collection...")
        Notification.create_indexes()
        print("✓ Notification indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ Notification indexes already exist, skipping")
    except Exception as e:
        print(f"✗ Notification error: {e}")

    try:
        print("Creating indexes for DeviceToken collection...")
        DeviceToken.create_indexes()
        print("✓ DeviceToken indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ DeviceToken indexes already exist, skipping")
    except Exception as e:
        print(f"✗ DeviceToken error: {e}")

    try:
        print("Creating indexes for ActiveSession collection...")
        ActiveSession.create_indexes()
        print("✓ ActiveSession indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ ActiveSession indexes already exist, skipping")
    except Exception as e:
        print(f"✗ ActiveSession error: {e}")

    try:
        print("Creating indexes for LoginActivity collection...")
        LoginActivity.create_indexes()
        print("✓ LoginActivity indexes created")
    except (DuplicateKeyError, OperationFailure):
        print("⚠ LoginActivity indexes already exist, skipping")
    except Exception as e:
        print(f"✗ LoginActivity error: {e}")

    print("-" * 50)
    print("Done! (Warnings are OK - indexes may already exist)")


if __name__ == "__main__":
    create_indexes()
