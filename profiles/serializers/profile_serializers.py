import re
from decimal import Decimal

from django.utils import timezone as django_timezone
from rest_framework import serializers

from accounts.serializers.base_serializers import InputSanitizationMixin
from profiles.models import (
    BUSINESS_TYPES,
    EDUCATION_LEVELS,
    EWALLET_USAGE_VALUES,
    HOUSING_STATUSES,
    INCOME_RANGES,
    LOAN_PAYMENT_HISTORIES,
    RISK_REVIEW_REASONS,
    UTILITY_PAYMENT_HISTORIES,
)

# Regex that matches valid Philippine location names:
# - Must start with a letter
# - May contain letters, spaces, hyphens, apostrophes, periods
# - Examples: "San Juan", "Sta. Rosa", "Sto. Tomas", "O'Donnell", "Baguio City"
MIN_CUSTOMER_AGE = 18
MAX_CUSTOMER_AGE = 100


def _money_field():
    return serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
        coerce_to_string=False,
    )


def _validate_location_name(value, field_label):
    """Shared validator for barangay / city / province fields."""
    if not value:
        return value  # allow blank (required check is handled per-field)
    stripped = value.strip()
    if not stripped[0].isalpha() or any(
        not (character.isalnum() or character in " '-.\u2019")
        for character in stripped
    ):
        raise serializers.ValidationError(
            f"{field_label} may only contain letters, numbers, spaces, hyphens, "
            "apostrophes and periods, and must start with a letter."
        )
    if re.search(r"\s{2,}", stripped):
        raise serializers.ValidationError(f"Please enter a valid {field_label} name.")
    return stripped


def _normalize_ph_mobile(value):
    if not value:
        return value
    cleaned = re.sub(r"[\s\-().]", "", value)
    if not re.fullmatch(r"(09\d{9}|\+639\d{9})", cleaned):
        raise serializers.ValidationError(
            "Enter a valid Philippine mobile number "
            "(e.g. 09171234567 or +639171234567)."
        )
    return "+63" + cleaned[1:] if cleaned.startswith("09") else cleaned


def _merged(serializer, data, field, default=None):
    if field in data:
        return data[field]
    return getattr(serializer.instance, field, default) if serializer.instance else default


def _require(data, field, value, message):
    if value is None or isinstance(value, str) and not value.strip():
        raise serializers.ValidationError({field: message})


class CustomerProfileSerializer(InputSanitizationMixin, serializers.Serializer):
    """Serializer for customer profile updates"""

    profile_revision = serializers.IntegerField(
        required=False, min_value=0, write_only=True
    )

    # Personal Information
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=["male", "female", "other", "prefer_not_to_say"],
        required=False,
        allow_null=True,
    )
    civil_status = serializers.ChoiceField(
        choices=["single", "married", "widowed", "separated"],
        required=False,
        allow_null=True,
    )
    nationality = serializers.CharField(max_length=50, required=False)
    mobile_number = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )

    # Address
    address_line1 = serializers.CharField(
        max_length=200, required=False, allow_blank=True
    )
    address_line2 = serializers.CharField(
        max_length=200, required=False, allow_blank=True
    )
    barangay = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city_municipality = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    province = serializers.CharField(max_length=100, required=False, allow_blank=True)
    zip_code = serializers.CharField(max_length=10, required=False, allow_blank=True)

    # Emergency Contact
    emergency_contact_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    emergency_contact_phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )
    emergency_contact_relationship = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )

    # Wallet
    wallet_address = serializers.CharField(
        max_length=42, required=False, allow_blank=True, allow_null=True
    )

    def validate_wallet_address(self, value):
        if not value:
            return value
        value = value.strip()
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
            raise serializers.ValidationError(
                "Enter a valid Ethereum address (0x followed by 40 hex characters)."
            )
        return value

    def validate_mobile_number(self, value):
        return _normalize_ph_mobile(value)

    def validate_emergency_contact_phone(self, value):
        return _normalize_ph_mobile(value)

    def validate_zip_code(self, value):
        if value and not re.fullmatch(r"\d{4}", value.strip()):
            raise serializers.ValidationError(
                "Enter a valid 4-digit Philippine ZIP code."
            )
        return value.strip() if value else value

    def validate_date_of_birth(self, value):
        if value is None:
            return value
        today = django_timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < MIN_CUSTOMER_AGE:
            raise serializers.ValidationError(
                f"Customer must be at least {MIN_CUSTOMER_AGE} years old."
            )
        if age > MAX_CUSTOMER_AGE:
            raise serializers.ValidationError(
                f"Customer age cannot exceed {MAX_CUSTOMER_AGE} years."
            )
        return value

    def validate_barangay(self, value):
        return _validate_location_name(value, "Barangay")

    def validate_city_municipality(self, value):
        return _validate_location_name(value, "City / Municipality")

    def validate_province(self, value):
        return _validate_location_name(value, "Province")


class CustomerProfileResponseSerializer(serializers.Serializer):
    """Serializer for customer profile response"""

    id = serializers.CharField(read_only=True)
    customer_id = serializers.CharField(read_only=True)
    date_of_birth = serializers.DateField(allow_null=True)
    gender = serializers.CharField(allow_null=True)
    civil_status = serializers.CharField(allow_null=True)
    nationality = serializers.CharField()
    mobile_number = serializers.CharField(allow_blank=True)
    address_line1 = serializers.CharField()
    address_line2 = serializers.CharField()
    barangay = serializers.CharField()
    city_municipality = serializers.CharField()
    province = serializers.CharField()
    zip_code = serializers.CharField()
    emergency_contact_name = serializers.CharField()
    emergency_contact_phone = serializers.CharField()
    emergency_contact_relationship = serializers.CharField()
    wallet_address = serializers.CharField(
        allow_null=True, allow_blank=True, required=False
    )
    profile_completed = serializers.BooleanField()
    completion_percentage = serializers.IntegerField()
    profile_revision = serializers.IntegerField()
    profile_completion_policy_version = serializers.CharField()
    profile_missing_fields = serializers.ListField(child=serializers.CharField())


class BusinessProfileSerializer(InputSanitizationMixin, serializers.Serializer):
    """Serializer for business profile updates"""

    profile_revision = serializers.IntegerField(
        required=False, min_value=0, write_only=True
    )

    # Business Information
    business_name = serializers.CharField(
        max_length=200, required=False, allow_blank=True
    )
    business_type = serializers.ChoiceField(
        choices=BUSINESS_TYPES, required=False, allow_null=True
    )
    business_type_other = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    business_description = serializers.CharField(
        max_length=500, required=False, allow_blank=True
    )

    # Location
    business_address = serializers.CharField(
        max_length=200, required=False, allow_blank=True
    )
    business_barangay = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    business_city = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    business_province = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )

    def validate_business_barangay(self, value):
        return _validate_location_name(value, "Business Barangay")

    def validate_business_city(self, value):
        return _validate_location_name(value, "Business City")

    def validate_business_province(self, value):
        return _validate_location_name(value, "Business Province")

    # Operations - canonical unit: months
    business_age_months = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Business age in months (canonical unit). Minimum 0 months.",
    )
    years_in_operation = serializers.DecimalField(
        max_digits=8,
        decimal_places=4,
        required=False,
        allow_null=True,
        min_value=0,
        coerce_to_string=False,
        write_only=True,
        help_text="Legacy alias for business age in years. Converted to months.",
    )
    is_registered = serializers.BooleanField(required=False)
    registration_type = serializers.ChoiceField(
        choices=["DTI", "SEC", "BIR", "none"], required=False, allow_null=True
    )
    registration_number = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )

    # Financial
    estimated_monthly_income = _money_field()
    income_range = serializers.ChoiceField(
        choices=INCOME_RANGES, required=False, allow_null=True
    )
    estimated_monthly_expenses = _money_field()
    number_of_employees = serializers.IntegerField(required=False, min_value=0)

    def validate(self, data):
        if "years_in_operation" in data:
            years = data.pop("years_in_operation")
            converted_months = None
            if years is not None:
                month_value = years * Decimal(12)
                if month_value != month_value.to_integral_value():
                    raise serializers.ValidationError(
                        {
                            "years_in_operation": (
                                "Business age must convert to a whole number of months."
                            )
                        }
                    )
                converted_months = int(month_value)

            if (
                "business_age_months" in data
                and data["business_age_months"] != converted_months
            ):
                raise serializers.ValidationError(
                    {
                        "years_in_operation": (
                            "Legacy years and canonical months must describe the "
                            "same business age."
                        )
                    }
                )
            data["business_age_months"] = converted_months

        business_type = _merged(self, data, "business_type")
        business_type_other = _merged(self, data, "business_type_other", "")
        if business_type == "other":
            _require(
                data,
                "business_type_other",
                business_type_other,
                "Please specify the business type.",
            )
        elif business_type is not None:
            data["business_type_other"] = ""

        is_registered = _merged(self, data, "is_registered")
        if is_registered is True:
            registration_type = _merged(self, data, "registration_type")
            registration_number = _merged(self, data, "registration_number", "")
            if registration_type in (None, "none"):
                raise serializers.ValidationError(
                    {"registration_type": "Select the active registration type."}
                )
            _require(
                data,
                "registration_number",
                registration_number,
                "Registration number is required for a registered business.",
            )
        elif is_registered is False:
            data["registration_type"] = None
            data["registration_number"] = ""
        return data


class NotificationPreferenceValuesSerializer(serializers.Serializer):
    """Strict JSON boolean values for the supported notification channels."""

    email_loan_updates = serializers.BooleanField(required=False)
    email_payment_reminders = serializers.BooleanField(required=False)
    email_promotions = serializers.BooleanField(required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Must be an object.")

        unknown = sorted(set(data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {key: "Unsupported notification preference." for key in unknown}
            )

        invalid_types = {
            key: "Must be a JSON boolean."
            for key, value in data.items()
            if type(value) is not bool
        }
        if invalid_types:
            raise serializers.ValidationError(invalid_types)
        return super().to_internal_value(data)


class NotificationPreferencesUpdateSerializer(serializers.Serializer):
    """Validated notification-preference update envelope."""

    preferences = NotificationPreferenceValuesSerializer(required=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Request body must be an object.")
        unknown = sorted(set(data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {key: "Unsupported request field." for key in unknown}
            )
        return super().to_internal_value(data)


class RiskReviewRequestSerializer(InputSanitizationMixin, serializers.Serializer):
    reason = serializers.ChoiceField(choices=RISK_REVIEW_REASONS)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )
    risk_calculated_revision = serializers.IntegerField(required=False, min_value=0)


class RiskReviewResolutionSerializer(InputSanitizationMixin, serializers.Serializer):
    status = serializers.ChoiceField(choices=("in_review", "resolved", "rejected"))
    resolution_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )
    review_revision = serializers.IntegerField(min_value=0)

    def validate(self, data):
        if data["status"] in {"resolved", "rejected"} and not data.get(
            "resolution_note", ""
        ).strip():
            raise serializers.ValidationError(
                {"resolution_note": "A resolution note is required."}
            )
        return data


class AlternativeDataSerializer(InputSanitizationMixin, serializers.Serializer):
    """Serializer for alternative credit data updates"""

    profile_revision = serializers.IntegerField(
        required=False, min_value=0, write_only=True
    )

    # Education & Employment
    education_level = serializers.ChoiceField(
        choices=EDUCATION_LEVELS, required=False, allow_null=True
    )
    employment_status = serializers.ChoiceField(
        choices=["employed", "self_employed", "unemployed", "retired", "student"],
        required=False,
        allow_null=True,
    )
    years_of_experience = serializers.FloatField(
        required=False, allow_null=True, min_value=0
    )

    # Housing
    housing_status = serializers.ChoiceField(
        choices=HOUSING_STATUSES,
        required=False,
        allow_null=True,
    )
    years_at_current_address = serializers.FloatField(
        required=False, allow_null=True, min_value=0
    )
    monthly_rent = _money_field()

    # Dependents
    number_of_dependents = serializers.IntegerField(required=False, min_value=0)
    household_income = _money_field()

    # Existing Credit
    has_existing_loans = serializers.BooleanField(required=False)
    existing_loan_amount = _money_field()
    existing_loan_source = serializers.ChoiceField(
        choices=["bank", "cooperative", "microfinance", "informal", "family", "none"],
        required=False,
        allow_null=True,
    )
    loan_payment_history = serializers.ChoiceField(
        choices=LOAN_PAYMENT_HISTORIES,
        required=False,
        allow_null=True,
    )

    # Digital Footprint
    has_bank_account = serializers.BooleanField(required=False)
    bank_account_duration = serializers.FloatField(
        required=False, allow_null=True, min_value=0
    )
    has_ewallet = serializers.BooleanField(required=False)
    ewallet_usage = serializers.ChoiceField(
        choices=EWALLET_USAGE_VALUES,
        required=False,
        allow_null=True,
    )

    # Utility Payments
    pays_utilities = serializers.BooleanField(required=False)
    utility_payment_history = serializers.ChoiceField(
        choices=UTILITY_PAYMENT_HISTORIES,
        required=False,
        allow_null=True,
    )

    # Social Capital
    is_coop_member = serializers.BooleanField(required=False)
    community_involvement = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, max_length=10
    )

    def validate(self, data):
        housing_status = _merged(self, data, "housing_status")
        if housing_status == "rented":
            _require(
                data,
                "monthly_rent",
                _merged(self, data, "monthly_rent"),
                "Monthly rent is required when housing is rented.",
            )
        elif housing_status is not None:
            data["monthly_rent"] = None

        has_loans = _merged(self, data, "has_existing_loans")
        if has_loans is True:
            amount = _merged(self, data, "existing_loan_amount")
            if amount is None or amount <= 0:
                raise serializers.ValidationError(
                    {"existing_loan_amount": "Enter an existing loan amount above zero."}
                )
            source = _merged(self, data, "existing_loan_source")
            if source in (None, "none"):
                raise serializers.ValidationError(
                    {"existing_loan_source": "Select the existing loan source."}
                )
            history = _merged(self, data, "loan_payment_history")
            if history in (None, "no_history"):
                raise serializers.ValidationError(
                    {"loan_payment_history": "Select the existing loan payment history."}
                )
        elif has_loans is False:
            data.update(
                existing_loan_amount=None,
                existing_loan_source=None,
                loan_payment_history=None,
            )

        for controller, dependent, message in (
            (
                "has_bank_account",
                "bank_account_duration",
                "Bank account duration is required when an account exists.",
            ),
            (
                "has_ewallet",
                "ewallet_usage",
                "E-wallet usage is required when an e-wallet exists.",
            ),
            (
                "pays_utilities",
                "utility_payment_history",
                "Utility payment history is required when utilities are paid.",
            ),
        ):
            enabled = _merged(self, data, controller)
            if enabled is True:
                _require(data, dependent, _merged(self, data, dependent), message)
            elif enabled is False:
                data[dependent] = None

        return data
