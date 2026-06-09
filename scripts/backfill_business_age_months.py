"""Backfill script to populate `business_age_months` from legacy `years_in_operation`.

Usage:
    ./venv/bin/python scripts/backfill_business_age_months.py

This will iterate `business_profiles` documents and set `business_age_months`
when missing and `years_in_operation` is present. It will multiply years by 12.
"""

from __future__ import annotations

import os
import sys
import logging

# Ensure Django settings are configured before importing `settings`
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Ensure project root is on sys.path so `config` package can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from django.conf import settings
import django

django.setup()

logger = logging.getLogger("backfill")
logging.basicConfig(level=logging.INFO)


def main(dry_run: bool = False):
    db = settings.MONGODB
    collection = db["business_profiles"]
    query = {
        "$and": [
            {"business_age_months": {"$in": [None, "", []]}},
            {"years_in_operation": {"$exists": True}},
        ]
    }
    total = collection.count_documents(query)
    if total == 0:
        logger.info("No documents to backfill")
        return 0

    logger.info(f"Found {total} documents to backfill")
    cursor = collection.find(query)
    updated = 0
    for doc in cursor:
        years = doc.get("years_in_operation")
        try:
            years_val = float(years)
            months = int(round(years_val * 12))
        except Exception:
            logger.warning(
                f"Skipping doc {doc.get('_id')} - cannot parse years_in_operation={years}"
            )
            continue

        if dry_run:
            logger.info(f"Would set business_age_months={months} for {doc.get('_id')}")
            updated += 1
            continue

        result = collection.update_one(
            {"_id": doc["_id"]}, {"$set": {"business_age_months": months}}
        )
        if result.modified_count:
            updated += 1

    logger.info(f"Backfilled {updated} documents")
    return 0


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    sys.exit(main(dry_run=dry))
