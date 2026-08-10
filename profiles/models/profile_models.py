"""
Profile Models for MSME Pathways

Collections:
- customer_profiles: Extended customer profile data
- business_profiles: Business/MSME information
- alternative_data: Alternative credit scoring data
"""

import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128
from bson.errors import InvalidId
from django.conf import settings
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from config.field_encryption import decrypt_fields, encrypt_fields

logger = logging.getLogger("profiles")

PROFILE_COMPLETION_POLICY_VERSION = "2026-08-09-v1"

PERSONAL_COMPLETION_FIELDS = (
    "date_of_birth",
    "gender",
    "civil_status",
    "nationality",
    "mobile_number",
    "address_line1",
    "barangay",
    "city_municipality",
    "province",
    "zip_code",
)
BUSINESS_COMPLETION_FIELDS = (
    "business_name",
    "business_type",
    "business_address",
    "business_barangay",
    "business_city",
    "business_province",
    "business_age_months",
    "is_registered",
    "estimated_monthly_income",
    "income_range",
    "estimated_monthly_expenses",
    "number_of_employees",
)
ALTERNATIVE_COMPLETION_FIELDS = (
    "education_level",
    "employment_status",
    "years_of_experience",
    "housing_status",
    "years_at_current_address",
    "number_of_dependents",
    "household_income",
    "has_existing_loans",
    "has_bank_account",
    "has_ewallet",
    "pays_utilities",
    "is_coop_member",
)


class ProfileRevisionConflict(RuntimeError):
    """Raised when a client updates a profile revision that is no longer current."""


def _is_completed_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _calculate_completion(profile, section, required_fields):
    missing = [
        f"{section}.{field}"
        for field in required_fields
        if not _is_completed_value(getattr(profile, field, None))
    ]
    profile.profile_missing_fields = missing
    profile.profile_completion_policy_version = PROFILE_COMPLETION_POLICY_VERSION
    completed = len(required_fields) - len(missing)
    profile.completion_percentage = int(completed / len(required_fields) * 100)
    profile.profile_completed = not missing
    return profile.completion_percentage


def _serialize_profile_fields(data, encrypted_fields, monetary_fields=()):
    serialized = encrypt_fields(data, encrypted_fields)

    for field in monetary_fields:
        if isinstance(serialized.get(field), Decimal):
            serialized[field] = Decimal128(serialized[field])

    for field, value in serialized.items():
        if isinstance(value, date) and not isinstance(value, datetime):
            serialized[field] = datetime.combine(
                value,
                time.min,
                tzinfo=timezone.utc,
            )

    return serialized


def _deserialize_profile_fields(data, encrypted_fields, monetary_fields=()):
    deserialized = decrypt_fields(data, encrypted_fields)
    for field in monetary_fields:
        if isinstance(deserialized.get(field), Decimal128):
            deserialized[field] = deserialized[field].to_decimal()
    return deserialized


def get_db():
    """Helper function to get the MongoDB database instance"""
    return settings.MONGODB


def _customer_id_candidates(customer_id):
    """Return both ObjectId and string forms for robust customer lookups."""
    if customer_id is None:
        return []

    candidates = []
    if isinstance(customer_id, ObjectId):
        candidates.append(customer_id)
        candidates.append(str(customer_id))
    else:
        customer_id_str = str(customer_id)
        candidates.append(customer_id_str)
        try:
            candidates.insert(0, ObjectId(customer_id_str))
        except InvalidId:
            logger.debug("Invalid ObjectId candidate: %s", customer_id_str)

    deduped = []
    seen = set()
    for value in candidates:
        marker = (type(value).__name__, str(value))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(value)

    return deduped


def _customer_lookup_query(customer_id):
    candidates = _customer_id_candidates(customer_id)
    if not candidates:
        return {"customer_id": customer_id}
    if len(candidates) == 1:
        return {"customer_id": candidates[0]}
    return {"customer_id": {"$in": candidates}}


def _find_latest_by_customer(collection_name, customer_id):
    """Fetch the most recently updated profile among mixed customer_id shapes."""
    db = get_db()
    collection = db[collection_name]
    query = _customer_lookup_query(customer_id)
    doc = collection.find_one(query, sort=[("updated_at", -1), ("created_at", -1)])
    return doc


def _atomic_get_or_create(model_class, customer_id):
    """Create one canonical profile shell without a find-then-insert race."""
    existing = model_class.find_by_customer(customer_id)
    if existing:
        return existing

    profile = model_class(customer_id=str(customer_id))
    data = profile.to_dict()
    data.pop("_id", None)
    collection = get_db()[model_class.collection_name]
    try:
        document = collection.find_one_and_update(
            _customer_lookup_query(customer_id),
            {"$setOnInsert": data},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        document = _find_latest_by_customer(model_class.collection_name, customer_id)
    if not document:
        raise RuntimeError("Profile creation was not persisted")
    return model_class.from_dict(document)


def _revision_query(document_id, expected_revision):
    query = {"_id": document_id}
    if expected_revision is None:
        return query
    expected_revision = int(expected_revision)
    if expected_revision == 0:
        query["$or"] = [
            {"profile_revision": 0},
            {"profile_revision": {"$exists": False}},
        ]
    else:
        query["profile_revision"] = expected_revision
    return query


def _finish_atomic_profile_update(model_class, document):
    """Persist completion for the newest observed revision without stale writes."""
    collection = get_db()[model_class.collection_name]
    for _attempt in range(10):
        profile = model_class.from_dict(document)
        profile.calculate_completion()
        revision = int(profile.profile_revision or 0)
        completed = collection.find_one_and_update(
            {"_id": profile._id, "profile_revision": revision},
            {
                "$set": {
                    "profile_completed": profile.profile_completed,
                    "completion_percentage": profile.completion_percentage,
                    "profile_completion_policy_version": (
                        profile.profile_completion_policy_version
                    ),
                    "profile_missing_fields": profile.profile_missing_fields,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if completed:
            return model_class.from_dict(completed)
        document = collection.find_one({"_id": profile._id})
        if not document:
            raise RuntimeError("Profile disappeared during update")
    raise RuntimeError("Profile completion could not settle after concurrent updates")


def _atomic_update_profile(
    profile,
    fields,
    *,
    expected_revision=None,
    additional_set=None,
    additional_inc=None,
):
    """Write only submitted fields and guard optional optimistic concurrency."""
    if not profile._id:
        raise ValueError("Profile must be saved before updating fields")

    protected = {"_id", "customer_id", "created_at", "profile_revision"}
    updates = {
        field: value
        for field, value in fields.items()
        if field not in protected and hasattr(profile, field)
    }
    if additional_set:
        updates.update(additional_set)
    updates["updated_at"] = datetime.now(timezone.utc)
    updates = _serialize_profile_fields(
        updates,
        profile.encrypted_fields,
        profile.monetary_fields,
    )
    increments = {"profile_revision": 1}
    if additional_inc:
        increments.update(additional_inc)

    document = get_db()[profile.collection_name].find_one_and_update(
        _revision_query(profile._id, expected_revision),
        {"$set": updates, "$inc": increments},
        return_document=ReturnDocument.AFTER,
    )
    if not document:
        if expected_revision is not None:
            raise ProfileRevisionConflict(
                "Profile was updated by another request; reload and retry"
            )
        raise RuntimeError("Profile update was not persisted")
    return _finish_atomic_profile_update(type(profile), document)


def _save_profile(profile):
    """Insert a new profile or guard a legacy full save with its revision."""
    collection = get_db()[profile.collection_name]
    profile.updated_at = datetime.now(timezone.utc)
    profile.calculate_completion()
    data = profile.to_dict()
    data.pop("_id", None)

    if not profile._id:
        result = collection.insert_one(data)
        profile._id = result.inserted_id
        return profile

    data.pop("profile_revision", None)
    document = collection.find_one_and_update(
        _revision_query(profile._id, profile.profile_revision),
        {"$set": data, "$inc": {"profile_revision": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not document:
        raise ProfileRevisionConflict(
            "Profile was updated by another request; reload and retry"
        )
    refreshed = type(profile).from_dict(document)
    profile.__dict__.update(refreshed.__dict__)
    return profile


# Business Type Options
BUSINESS_TYPES = [
    "sari_sari_store",  # Sari-sari store
    "market_vendor",  # Market vendor/stallholder
    "home_based_seller",  # Home-based seller
    "food_vendor",  # Food vendor/eatery
    "transport_service",  # Tricycle/jeepney operator
    "freelancer",  # Freelance services
    "agriculture",  # Small-scale farming
    "manufacturing",  # Small manufacturing
    "retail_trade",  # Retail trade
    "other",  # Other
]

# Education Level Options
EDUCATION_LEVELS = [
    "no_formal",  # No formal education
    "elementary",  # Elementary
    "high_school",  # High school
    "vocational",  # Vocational/Technical
    "college_undergraduate",  # Some college
    "college_graduate",  # College graduate
    "postgraduate",  # Postgraduate
]

# Income Range Options (Monthly in PHP)
INCOME_RANGES = [
    "below_10000",  # Below ₱10,000
    "10000_20000",  # ₱10,000 - ₱20,000
    "20000_30000",  # ₱20,000 - ₱30,000
    "30000_50000",  # ₱30,000 - ₱50,000
    "50000_100000",  # ₱50,000 - ₱100,000
    "above_100000",  # Above ₱100,000
]

# Canonical alternative-data values shared by API validation and scoring.
HOUSING_STATUSES = (
    "owned",
    "rented",
    "living_with_family",
    "company_provided",
)
LOAN_PAYMENT_HISTORIES = (
    "on_time",
    "sometimes_late",
    "often_late",
    "defaulted",
    "no_history",
)
UTILITY_PAYMENT_HISTORIES = ("on_time", "sometimes_late", "often_late")
EWALLET_USAGE_VALUES = ("daily", "weekly", "monthly", "rarely", "never")


class CustomerProfile:
    """
    Extended customer profile data.

    Stores additional personal information for loan pre-qualification.
    """

    collection_name = "customer_profiles"
    encrypted_fields = (
        "mobile_number",
        "address_line1",
        "address_line2",
        "barangay",
        "city_municipality",
        "province",
        "zip_code",
        "emergency_contact_name",
        "emergency_contact_phone",
    )
    monetary_fields = ()

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = kwargs.get("customer_id")  # Reference to Customer

        # Personal Information
        self.date_of_birth = kwargs.get("date_of_birth")
        self.gender = kwargs.get("gender")  # male, female, other, prefer_not_to_say
        self.civil_status = kwargs.get(
            "civil_status"
        )  # single, married, widowed, separated
        self.nationality = kwargs.get("nationality", "Filipino")
        self.mobile_number = kwargs.get(
            "mobile_number", ""
        )  # Philippine mobile e.g. +639XXXXXXXXX

        # Address Information
        self.address_line1 = kwargs.get("address_line1", "")
        self.address_line2 = kwargs.get("address_line2", "")
        self.barangay = kwargs.get("barangay", "")
        self.city_municipality = kwargs.get("city_municipality", "")
        self.province = kwargs.get("province", "")
        self.zip_code = kwargs.get("zip_code", "")

        # Emergency Contact
        self.emergency_contact_name = kwargs.get("emergency_contact_name", "")
        self.emergency_contact_phone = kwargs.get("emergency_contact_phone", "")
        self.emergency_contact_relationship = kwargs.get(
            "emergency_contact_relationship", ""
        )

        # Wallet
        self.wallet_address = kwargs.get(
            "wallet_address"
        )  # Ethereum address (0x + 40 hex)

        # Profile Completion
        self.profile_completed = kwargs.get("profile_completed", False)
        self.completion_percentage = kwargs.get("completion_percentage", 0)
        self.profile_revision = kwargs.get("profile_revision", 0)
        self.profile_completion_policy_version = kwargs.get(
            "profile_completion_policy_version", PROFILE_COMPLETION_POLICY_VERSION
        )
        self.profile_missing_fields = kwargs.get("profile_missing_fields", [])

        # Timestamps
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        # Convert date_of_birth to datetime for MongoDB compatibility
        dob = self.date_of_birth
        if isinstance(dob, date) and not isinstance(dob, datetime):
            dob = datetime.combine(dob, time.min)

        data = {
            "customer_id": self.customer_id,
            "date_of_birth": dob,
            "gender": self.gender,
            "civil_status": self.civil_status,
            "nationality": self.nationality,
            "mobile_number": self.mobile_number,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "barangay": self.barangay,
            "city_municipality": self.city_municipality,
            "province": self.province,
            "zip_code": self.zip_code,
            "emergency_contact_name": self.emergency_contact_name,
            "emergency_contact_phone": self.emergency_contact_phone,
            "emergency_contact_relationship": self.emergency_contact_relationship,
            "wallet_address": self.wallet_address,
            "profile_completed": self.profile_completed,
            "completion_percentage": self.completion_percentage,
            "profile_revision": self.profile_revision,
            "profile_completion_policy_version": (
                self.profile_completion_policy_version
            ),
            "profile_missing_fields": self.profile_missing_fields,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return _serialize_profile_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        profile = cls(**_deserialize_profile_fields(data, cls.encrypted_fields))
        profile.calculate_completion()
        return profile

    def calculate_completion(self):
        """Calculate profile completion percentage"""
        return _calculate_completion(
            self,
            "personal",
            PERSONAL_COMPLETION_FIELDS,
        )

    def save(self):
        return _save_profile(self)

    def update_fields(self, fields, expected_revision=None):
        return _atomic_update_profile(
            self,
            fields,
            expected_revision=expected_revision,
        )

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find_by_customer(cls, customer_id):
        return cls.from_dict(_find_latest_by_customer(cls.collection_name, customer_id))

    @classmethod
    def get_or_create(cls, customer_id):
        return _atomic_get_or_create(cls, customer_id)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer_id", unique=True)
        collection.create_index("updated_at")


class BusinessProfile:
    """
    Business/MSME information for loan pre-qualification.
    """

    collection_name = "business_profiles"
    encrypted_fields = (
        "business_address",
        "business_barangay",
        "business_city",
        "business_province",
        "registration_number",
        "estimated_monthly_income",
        "estimated_monthly_expenses",
    )
    monetary_fields = (
        "estimated_monthly_income",
        "estimated_monthly_expenses",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = kwargs.get("customer_id")

        # Business Information
        self.business_name = kwargs.get("business_name", "")
        self.business_type = kwargs.get("business_type")  # From BUSINESS_TYPES
        self.business_type_other = kwargs.get(
            "business_type_other", ""
        )  # If type is 'other'
        self.business_description = kwargs.get("business_description", "")

        # Location
        self.business_address = kwargs.get("business_address", "")
        self.business_barangay = kwargs.get("business_barangay", "")
        self.business_city = kwargs.get("business_city", "")
        self.business_province = kwargs.get("business_province", "")

        # Operations
        # Canonical unit: months (not years)
        # Support both field names for backwards compatibility
        # Use explicit None check to handle 0 as valid value
        _age_months = kwargs.get("business_age_months")
        _years_op = kwargs.get("years_in_operation")
        # If caller supplied canonical months, use it. Otherwise, if a legacy
        # `years_in_operation` is provided, treat it as years and convert to months
        # (rounded to nearest integer month). This keeps backward compatibility
        # while normalizing stored data to months.
        if _age_months is not None:
            self.business_age_months = _age_months
        elif _years_op is not None:
            try:
                years = float(_years_op)
                self.business_age_months = round(years * 12)
            except (ValueError, TypeError):
                self.business_age_months = _years_op
        else:
            self.business_age_months = None
        self.is_registered = kwargs.get("is_registered")  # DTI/SEC registered
        self.registration_type = kwargs.get("registration_type")  # DTI, SEC, BIR
        self.registration_number = kwargs.get("registration_number", "")

        # Financial
        self.estimated_monthly_income = kwargs.get("estimated_monthly_income")  # Float
        self.income_range = kwargs.get("income_range")  # From INCOME_RANGES
        self.estimated_monthly_expenses = kwargs.get("estimated_monthly_expenses")
        self.number_of_employees = kwargs.get("number_of_employees")

        # Profile Completion
        self.profile_completed = kwargs.get("profile_completed", False)
        self.completion_percentage = kwargs.get("completion_percentage", 0)
        self.profile_revision = kwargs.get("profile_revision", 0)
        self.profile_completion_policy_version = kwargs.get(
            "profile_completion_policy_version", PROFILE_COMPLETION_POLICY_VERSION
        )
        self.profile_missing_fields = kwargs.get("profile_missing_fields", [])

        # Timestamps
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "customer_id": self.customer_id,
            "business_name": self.business_name,
            "business_type": self.business_type,
            "business_type_other": self.business_type_other,
            "business_description": self.business_description,
            "business_address": self.business_address,
            "business_barangay": self.business_barangay,
            "business_city": self.business_city,
            "business_province": self.business_province,
            "business_age_months": self.business_age_months,
            "is_registered": self.is_registered,
            "registration_type": self.registration_type,
            "registration_number": self.registration_number,
            "estimated_monthly_income": self.estimated_monthly_income,
            "income_range": self.income_range,
            "estimated_monthly_expenses": self.estimated_monthly_expenses,
            "number_of_employees": self.number_of_employees,
            "profile_completed": self.profile_completed,
            "completion_percentage": self.completion_percentage,
            "profile_revision": self.profile_revision,
            "profile_completion_policy_version": (
                self.profile_completion_policy_version
            ),
            "profile_missing_fields": self.profile_missing_fields,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return _serialize_profile_fields(
            data,
            self.encrypted_fields,
            self.monetary_fields,
        )

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        profile = cls(
            **_deserialize_profile_fields(
                data,
                cls.encrypted_fields,
                cls.monetary_fields,
            )
        )
        profile.calculate_completion()
        return profile

    def save(self):
        return _save_profile(self)

    def update_fields(self, fields, expected_revision=None):
        return _atomic_update_profile(
            self,
            fields,
            expected_revision=expected_revision,
        )

    def calculate_completion(self):
        """Calculate business profile completion."""
        required = list(BUSINESS_COMPLETION_FIELDS)
        if self.business_type == "other":
            required.append("business_type_other")
        if self.is_registered is True:
            required.extend(("registration_type", "registration_number"))
        return _calculate_completion(self, "business", required)

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find_by_customer(cls, customer_id):
        return cls.from_dict(_find_latest_by_customer(cls.collection_name, customer_id))

    @classmethod
    def get_or_create(cls, customer_id):
        return _atomic_get_or_create(cls, customer_id)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer_id", unique=True)


class AlternativeData:
    """
    Alternative credit data for users with no formal credit history.

    This data is used for AI-driven credit scoring and loan pre-qualification.
    """

    collection_name = "alternative_data"
    encrypted_fields = (
        "existing_loan_source",
        "household_income",
        "existing_loan_amount",
        "monthly_rent",
    )
    monetary_fields = (
        "monthly_rent",
        "household_income",
        "existing_loan_amount",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = kwargs.get("customer_id")

        # Education & Employment
        self.education_level = kwargs.get("education_level")  # From EDUCATION_LEVELS
        self.employment_status = kwargs.get(
            "employment_status"
        )  # employed, self_employed, unemployed
        self.years_of_experience = kwargs.get("years_of_experience")

        # Housing
        self.housing_status = kwargs.get(
            "housing_status"
        )  # owned, rented, living_with_family
        self.years_at_current_address = kwargs.get("years_at_current_address")
        self.monthly_rent = kwargs.get("monthly_rent")  # If renting

        # Dependents & Family
        self.number_of_dependents = kwargs.get("number_of_dependents")
        self.household_income = kwargs.get("household_income")

        # Existing Credit
        self.has_existing_loans = kwargs.get("has_existing_loans")
        self.existing_loan_amount = kwargs.get("existing_loan_amount")
        self.existing_loan_source = kwargs.get(
            "existing_loan_source"
        )  # bank, cooperative, informal
        self.loan_payment_history = kwargs.get(
            "loan_payment_history"
        )  # on_time, late, defaulted

        # Digital Footprint (optional)
        self.has_bank_account = kwargs.get("has_bank_account")
        self.bank_account_duration = kwargs.get("bank_account_duration")  # Years
        self.has_ewallet = kwargs.get("has_ewallet")  # GCash, Wallet (ETH), etc.
        self.ewallet_usage = kwargs.get(
            "ewallet_usage"
        )  # daily, weekly, monthly, rarely

        # Utility Payments
        self.pays_utilities = kwargs.get("pays_utilities")
        self.utility_payment_history = kwargs.get(
            "utility_payment_history"
        )  # on_time, late

        # Social Capital
        self.is_coop_member = kwargs.get("is_coop_member")
        self.community_involvement = kwargs.get(
            "community_involvement", []
        )  # List of orgs

        # Risk Score (calculated by AI)
        self.risk_score = kwargs.get("risk_score")  # 0-100, higher = lower risk
        self.risk_category = kwargs.get("risk_category")  # low, medium, high
        self.score_calculated_at = kwargs.get("score_calculated_at")
        self.risk_score_status = kwargs.get("risk_score_status", "not_calculated")
        self.risk_score_policy_version = kwargs.get("risk_score_policy_version")
        self.risk_score_use = kwargs.get("risk_score_use", "informational_only")
        self.risk_score_manual_review_required = kwargs.get(
            "risk_score_manual_review_required", True
        )
        self.risk_input_revision = kwargs.get("risk_input_revision", 0)
        self.risk_calculated_revision = kwargs.get("risk_calculated_revision")
        self.risk_score_breakdown = kwargs.get("risk_score_breakdown", {})
        self.risk_score_reason_codes = kwargs.get("risk_score_reason_codes", [])
        self.risk_score_error_code = kwargs.get("risk_score_error_code", "")
        self.risk_score_task_id = kwargs.get("risk_score_task_id")
        self.risk_score_requested_at = kwargs.get("risk_score_requested_at")
        self.risk_score_failed_at = kwargs.get("risk_score_failed_at")
        self.risk_score_last_task_status = kwargs.get("risk_score_last_task_status")
        self.risk_score_last_stale_revision = kwargs.get(
            "risk_score_last_stale_revision"
        )
        self.risk_score_stale_at = kwargs.get("risk_score_stale_at")

        # Profile Completion
        self.profile_completed = kwargs.get("profile_completed", False)
        self.completion_percentage = kwargs.get("completion_percentage", 0)
        self.profile_revision = kwargs.get("profile_revision", 0)
        self.profile_completion_policy_version = kwargs.get(
            "profile_completion_policy_version", PROFILE_COMPLETION_POLICY_VERSION
        )
        self.profile_missing_fields = kwargs.get("profile_missing_fields", [])

        # Timestamps
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "customer_id": self.customer_id,
            "education_level": self.education_level,
            "employment_status": self.employment_status,
            "years_of_experience": self.years_of_experience,
            "housing_status": self.housing_status,
            "years_at_current_address": self.years_at_current_address,
            "monthly_rent": self.monthly_rent,
            "number_of_dependents": self.number_of_dependents,
            "household_income": self.household_income,
            "has_existing_loans": self.has_existing_loans,
            "existing_loan_amount": self.existing_loan_amount,
            "existing_loan_source": self.existing_loan_source,
            "loan_payment_history": self.loan_payment_history,
            "has_bank_account": self.has_bank_account,
            "bank_account_duration": self.bank_account_duration,
            "has_ewallet": self.has_ewallet,
            "ewallet_usage": self.ewallet_usage,
            "pays_utilities": self.pays_utilities,
            "utility_payment_history": self.utility_payment_history,
            "is_coop_member": self.is_coop_member,
            "community_involvement": self.community_involvement,
            "risk_score": self.risk_score,
            "risk_category": self.risk_category,
            "score_calculated_at": self.score_calculated_at,
            "risk_score_status": self.risk_score_status,
            "risk_score_policy_version": self.risk_score_policy_version,
            "risk_score_use": self.risk_score_use,
            "risk_score_manual_review_required": self.risk_score_manual_review_required,
            "risk_input_revision": self.risk_input_revision,
            "risk_calculated_revision": self.risk_calculated_revision,
            "risk_score_breakdown": self.risk_score_breakdown,
            "risk_score_reason_codes": self.risk_score_reason_codes,
            "risk_score_error_code": self.risk_score_error_code,
            "risk_score_task_id": self.risk_score_task_id,
            "risk_score_requested_at": self.risk_score_requested_at,
            "risk_score_failed_at": self.risk_score_failed_at,
            "risk_score_last_task_status": self.risk_score_last_task_status,
            "risk_score_last_stale_revision": self.risk_score_last_stale_revision,
            "risk_score_stale_at": self.risk_score_stale_at,
            "profile_completed": self.profile_completed,
            "completion_percentage": self.completion_percentage,
            "profile_revision": self.profile_revision,
            "profile_completion_policy_version": (
                self.profile_completion_policy_version
            ),
            "profile_missing_fields": self.profile_missing_fields,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return _serialize_profile_fields(
            data,
            self.encrypted_fields,
            self.monetary_fields,
        )

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        profile = cls(
            **_deserialize_profile_fields(
                data,
                cls.encrypted_fields,
                cls.monetary_fields,
            )
        )
        profile.calculate_completion()
        return profile

    def save(self):
        return _save_profile(self)

    def update_inputs(self, fields, expected_revision=None):
        """Atomically update validated inputs and create a new scoring revision."""

        if not self._id:
            raise ValueError("Alternative data must be saved before updating inputs")

        now = datetime.now(timezone.utc)
        return _atomic_update_profile(
            self,
            fields,
            expected_revision=expected_revision,
            additional_set={
                "risk_score": None,
                "risk_category": None,
                "score_calculated_at": None,
                "risk_score_status": "pending",
                "risk_score_policy_version": None,
                "risk_score_use": "informational_only",
                "risk_score_manual_review_required": True,
                "risk_calculated_revision": None,
                "risk_score_breakdown": {},
                "risk_score_reason_codes": [],
                "risk_score_error_code": "",
                "risk_score_task_id": None,
                "risk_score_requested_at": now,
                "risk_score_failed_at": None,
            },
            additional_inc={"risk_input_revision": 1},
        )

    def calculate_completion(self):
        """Calculate alternative data completion."""
        required = list(ALTERNATIVE_COMPLETION_FIELDS)
        if self.housing_status == "rented":
            required.append("monthly_rent")
        if self.has_existing_loans is True:
            required.extend(
                (
                    "existing_loan_amount",
                    "existing_loan_source",
                    "loan_payment_history",
                )
            )
        if self.has_bank_account is True:
            required.append("bank_account_duration")
        if self.has_ewallet is True:
            required.append("ewallet_usage")
        if self.pays_utilities is True:
            required.append("utility_payment_history")
        return _calculate_completion(self, "alternative", required)

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find_by_customer(cls, customer_id):
        return cls.from_dict(_find_latest_by_customer(cls.collection_name, customer_id))

    @classmethod
    def get_or_create(cls, customer_id):
        return _atomic_get_or_create(cls, customer_id)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer_id", unique=True)
        collection.create_index("risk_score")
        collection.create_index(
            [("risk_score_status", 1), ("risk_score_requested_at", 1)]
        )
