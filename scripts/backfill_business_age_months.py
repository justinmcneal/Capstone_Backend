"""Safely reconcile legacy business years into canonical whole months.

Usage:
    .venv/bin/python scripts/backfill_business_age_months.py
    .venv/bin/python scripts/backfill_business_age_months.py --apply

The default invocation is inventory-only. ``--apply`` is required for writes.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.conf import settings

django.setup()

from profiles.models import BusinessProfile

logger = logging.getLogger("profiles")


def _whole_months(years):
    try:
        value = Decimal(str(years)) * Decimal(12)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        return None
    return int(value)


def _missing_canonical_age_query():
    return {
        "$or": [
            {"business_age_months": {"$exists": False}},
            {"business_age_months": None},
            {"business_age_months": ""},
        ]
    }


def main(*, apply=False):
    collection = settings.MONGODB[BusinessProfile.collection_name]
    query = {
        "$and": [
            _missing_canonical_age_query(),
            {"years_in_operation": {"$exists": True}},
        ]
    }
    documents = list(collection.find(query))
    eligible = []
    invalid = []

    for document in documents:
        months = _whole_months(document.get("years_in_operation"))
        if months is None:
            invalid.append(document.get("_id"))
        else:
            eligible.append((document, months))

    logger.info(
        "Business-age reconciliation: found=%s eligible=%s invalid=%s mode=%s",
        len(documents),
        len(eligible),
        len(invalid),
        "apply" if apply else "dry-run",
    )
    for document_id in invalid:
        logger.warning("Invalid legacy business age requires review: %s", document_id)

    if not apply:
        for document, months in eligible:
            logger.info(
                "Would set business_age_months=%s for %s", months, document.get("_id")
            )
        return {"found": len(documents), "eligible": len(eligible), "updated": 0}

    updated = 0
    for document, months in eligible:
        candidate = dict(document)
        candidate["business_age_months"] = months
        profile = BusinessProfile.from_dict(candidate)
        revision = document.get("profile_revision")
        revision_query = (
            {"profile_revision": revision}
            if revision is not None
            else {"profile_revision": {"$exists": False}}
        )
        result = collection.update_one(
            {
                "_id": document["_id"],
                "$and": [_missing_canonical_age_query(), revision_query],
            },
            {
                "$set": {
                    "business_age_months": months,
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                    "profile_completion_policy_version": (
                        profile.profile_completion_policy_version
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$inc": {"profile_revision": 1},
            },
        )
        updated += result.modified_count

    logger.info("Business-age reconciliation updated=%s", updated)
    return {"found": len(documents), "eligible": len(eligible), "updated": updated}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist eligible conversions. Omit for an inventory-only dry run.",
    )
    arguments = parser.parse_args()
    result = main(apply=arguments.apply)
    print(
        "Business-age reconciliation complete: "
        f"found={result['found']}, eligible={result['eligible']}, "
        f"updated={result['updated']}."
    )
