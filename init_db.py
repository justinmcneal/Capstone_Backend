"""
Initialize MongoDB database by creating required indexes.
Run this script after migrating from MongoEngine to PyMongo.

Usage:
    python init_db.py
"""

import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounts.models import Customer, BlacklistedToken, RefreshTokenEntry
from pymongo.errors import DuplicateKeyError


def create_indexes():
    """Create indexes for all models"""
    print("Creating indexes for MongoDB collections...")
    print("-" * 50)
    
    # Customer indexes
    try:
        print("Creating indexes for Customer collection...")
        Customer.create_indexes()
        print("✓ Customer indexes created")
    except DuplicateKeyError as e:
        print("⚠ Customer indexes already exist or have duplicate data")
    except Exception as e:
        print(f"✗ Customer error: {e}")
    
    # BlacklistedToken indexes
    try:
        print("Creating indexes for BlacklistedToken collection...")
        BlacklistedToken.create_indexes()
        print("✓ BlacklistedToken indexes created")
    except DuplicateKeyError as e:
        print("⚠ BlacklistedToken: Duplicate tokens exist in database")
        print("  → Cleaning up duplicates...")
        cleanup_duplicate_tokens()
        print("  → Retrying index creation...")
        try:
            BlacklistedToken.create_indexes()
            print("✓ BlacklistedToken indexes created after cleanup")
        except Exception:
            print("  → Index may already exist, continuing...")
    except Exception as e:
        print(f"✗ BlacklistedToken error: {e}")
    
    # RefreshTokenEntry indexes
    try:
        print("Creating indexes for RefreshTokenEntry collection...")
        RefreshTokenEntry.create_indexes()
        print("✓ RefreshTokenEntry indexes created")
    except DuplicateKeyError as e:
        print("⚠ RefreshTokenEntry indexes already exist or have duplicate data")
    except Exception as e:
        print(f"✗ RefreshTokenEntry error: {e}")
    
    print("-" * 50)
    print("Index initialization complete!")


def cleanup_duplicate_tokens():
    """Remove duplicate tokens from blacklisted_tokens collection"""
    from django.conf import settings
    
    db = settings.MONGODB
    if not db:
        print("  → Database not available for cleanup")
        return
    
    collection = db['blacklisted_tokens']
    
    # Find duplicates and keep only the first one
    pipeline = [
        {"$group": {
            "_id": "$token",
            "count": {"$sum": 1},
            "ids": {"$push": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    
    duplicates = list(collection.aggregate(pipeline))
    removed = 0
    
    for doc in duplicates:
        # Keep the first, remove the rest
        ids_to_remove = doc['ids'][1:]
        collection.delete_many({"_id": {"$in": ids_to_remove}})
        removed += len(ids_to_remove)
    
    if removed > 0:
        print(f"  → Removed {removed} duplicate tokens")
    else:
        print("  → No duplicates found to remove")


if __name__ == "__main__":
    create_indexes()
