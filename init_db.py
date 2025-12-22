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


def create_indexes():
    """Create indexes for all models"""
    print("Creating indexes for MongoDB collections...")
    
    try:
        # Create indexes for Customer
        print("Creating indexes for Customer collection...")
        Customer.create_indexes()
        print("✓ Customer indexes created")
        
        # Create indexes for BlacklistedToken
        print("Creating indexes for BlacklistedToken collection...")
        BlacklistedToken.create_indexes()
        print("✓ BlacklistedToken indexes created")
        
        # Create indexes for RefreshTokenEntry
        print("Creating indexes for RefreshTokenEntry collection...")
        RefreshTokenEntry.create_indexes()
        print("✓ RefreshTokenEntry indexes created")
        
        print("\nAll indexes created successfully!")
        
    except Exception as e:
        print(f"\n✗ Error creating indexes: {str(e)}")
        raise


if __name__ == "__main__":
    create_indexes()
