"""
Profile Models for MSME Pathways

Collections:
- customer_profiles: Extended customer profile data
- business_profiles: Business/MSME information
- alternative_data: Alternative credit scoring data
"""

from datetime import datetime, date, time, timezone
from bson import ObjectId
from django.conf import settings
from config.field_encryption import decrypt_fields, encrypt_fields


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
        except Exception:
            pass

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def calculate_completion(self):
        """Calculate profile completion percentage"""
        fields = [
            self.date_of_birth,
            self.gender,
            self.civil_status,
            self.address_line1,
            self.barangay,
            self.city_municipality,
            self.province,
        ]
        filled = sum(1 for f in fields if f)
        self.completion_percentage = int((filled / len(fields)) * 100)
        self.profile_completed = self.completion_percentage == 100
        return self.completion_percentage

    def save(self):
        db = get_db()
        collection = db[self.collection_name]

        self.updated_at = datetime.now(timezone.utc)
        self.calculate_completion()
        data = self.to_dict()
        data.pop("_id", None)

        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id

        return self

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
        profile = cls.find_by_customer(customer_id)
        if not profile:
            profile = cls(customer_id=str(customer_id))
            profile.save()
        return profile

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
        self.business_age_months = _age_months if _age_months is not None else _years_op
        self.is_registered = kwargs.get("is_registered", False)  # DTI/SEC registered
        self.registration_type = kwargs.get("registration_type")  # DTI, SEC, BIR
        self.registration_number = kwargs.get("registration_number", "")

        # Financial
        self.estimated_monthly_income = kwargs.get("estimated_monthly_income")  # Float
        self.income_range = kwargs.get("income_range")  # From INCOME_RANGES
        self.estimated_monthly_expenses = kwargs.get("estimated_monthly_expenses")
        self.number_of_employees = kwargs.get("number_of_employees", 0)

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def save(self):
        db = get_db()
        collection = db[self.collection_name]

        self.updated_at = datetime.now(timezone.utc)
        data = self.to_dict()
        data.pop("_id", None)

        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id

        return self

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
        profile = cls.find_by_customer(customer_id)
        if not profile:
            profile = cls(customer_id=str(customer_id))
            profile.save()
        return profile

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
        self.number_of_dependents = kwargs.get("number_of_dependents", 0)
        self.household_income = kwargs.get("household_income")

        # Existing Credit
        self.has_existing_loans = kwargs.get("has_existing_loans", False)
        self.existing_loan_amount = kwargs.get("existing_loan_amount")
        self.existing_loan_source = kwargs.get(
            "existing_loan_source"
        )  # bank, cooperative, informal
        self.loan_payment_history = kwargs.get(
            "loan_payment_history"
        )  # on_time, late, defaulted

        # Digital Footprint (optional)
        self.has_bank_account = kwargs.get("has_bank_account", False)
        self.bank_account_duration = kwargs.get("bank_account_duration")  # Years
        self.has_ewallet = kwargs.get("has_ewallet", False)  # GCash, Wallet (ETH), etc.
        self.ewallet_usage = kwargs.get(
            "ewallet_usage"
        )  # daily, weekly, monthly, rarely

        # Utility Payments
        self.pays_utilities = kwargs.get("pays_utilities", False)
        self.utility_payment_history = kwargs.get(
            "utility_payment_history"
        )  # on_time, late

        # Social Capital
        self.is_coop_member = kwargs.get("is_coop_member", False)
        self.community_involvement = kwargs.get(
            "community_involvement", []
        )  # List of orgs

        # Risk Score (calculated by AI)
        self.risk_score = kwargs.get("risk_score")  # 0-100, higher = lower risk
        self.risk_category = kwargs.get("risk_category")  # low, medium, high
        self.score_calculated_at = kwargs.get("score_calculated_at")

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**data)

    def save(self):
        db = get_db()
        collection = db[self.collection_name]

        self.updated_at = datetime.now(timezone.utc)
        data = self.to_dict()
        data.pop("_id", None)

        if self._id:
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id

        return self

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
        profile = cls.find_by_customer(customer_id)
        if not profile:
            profile = cls(customer_id=str(customer_id))
            profile.save()
        return profile

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer_id", unique=True)
        collection.create_index("risk_score")
