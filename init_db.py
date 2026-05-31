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

from accounts.models import (  # noqa: E402
    Admin,
    BlacklistedToken,
    Consent,
    Customer,
    LoanOfficer,
    RefreshTokenEntry,
)
from pymongo.errors import DuplicateKeyError, OperationFailure  # noqa: E402
from django.conf import settings  # noqa: E402
from profiles.models import (  # noqa: E402
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
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

    print("-" * 50)
    print("Done! (Warnings are OK - indexes may already exist)")


if __name__ == "__main__":
    create_indexes()
