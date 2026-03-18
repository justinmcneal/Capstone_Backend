from rest_framework import serializers
from profiles.models import BUSINESS_TYPES, EDUCATION_LEVELS, INCOME_RANGES
from accounts.serializers.base_serializers import InputSanitizationMixin
import re

# Regex that matches valid Philippine location names:
# - Must start with a letter
# - May contain letters, spaces, hyphens, apostrophes, periods
# - Examples: "San Juan", "Sta. Rosa", "Sto. Tomas", "O'Donnell", "Baguio City"
_LOCATION_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z\s'\-.]*$")


def _validate_location_name(value, field_label):
    """Shared validator for barangay / city / province fields."""
    if not value:
        return value  # allow blank (required check is handled per-field)
    stripped = value.strip()
    if not _LOCATION_NAME_RE.match(stripped):
        raise serializers.ValidationError(
            f"{field_label} may only contain letters, spaces, hyphens, "
            "apostrophes and periods."
        )
    if re.search(r'\s{2,}', stripped):
        raise serializers.ValidationError(
            f"Please enter a valid {field_label} name."
        )
    return stripped


class CustomerProfileSerializer(InputSanitizationMixin, serializers.Serializer):
    """Serializer for customer profile updates"""
    
    # Personal Information
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=['male', 'female', 'other', 'prefer_not_to_say'],
        required=False,
        allow_null=True
    )
    civil_status = serializers.ChoiceField(
        choices=['single', 'married', 'widowed', 'separated'],
        required=False,
        allow_null=True
    )
    nationality = serializers.CharField(max_length=50, required=False)
    mobile_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    
    # Address
    address_line1 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    address_line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    barangay = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city_municipality = serializers.CharField(max_length=100, required=False, allow_blank=True)
    province = serializers.CharField(max_length=100, required=False, allow_blank=True)
    zip_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    
    # Emergency Contact
    emergency_contact_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    emergency_contact_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    emergency_contact_relationship = serializers.CharField(max_length=50, required=False, allow_blank=True)

    # Wallet
    wallet_address = serializers.CharField(max_length=42, required=False, allow_blank=True, allow_null=True)

    def validate_wallet_address(self, value):
        if not value:
            return value
        value = value.strip()
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', value):
            raise serializers.ValidationError(
                'Enter a valid Ethereum address (0x followed by 40 hex characters).'
            )
        return value

    def validate_mobile_number(self, value):
        if not value:
            return value  # optional field
        cleaned = re.sub(r'[\s\-().]', '', value)
        # Accept 09XXXXXXXXX (11 digits) or +639XXXXXXXXX (13 chars)
        if not re.fullmatch(r'(09\d{9}|\+639\d{9})', cleaned):
            raise serializers.ValidationError(
                'Enter a valid Philippine mobile number '
                '(e.g. 09171234567 or +639171234567).'
            )
        # Normalize to +639XXXXXXXXX
        if cleaned.startswith('09'):
            cleaned = '+63' + cleaned[1:]
        return cleaned

    def validate_barangay(self, value):
        return _validate_location_name(value, 'Barangay')

    def validate_city_municipality(self, value):
        return _validate_location_name(value, 'City / Municipality')

    def validate_province(self, value):
        return _validate_location_name(value, 'Province')


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
    wallet_address = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    profile_completed = serializers.BooleanField()
    completion_percentage = serializers.IntegerField()


class BusinessProfileSerializer(InputSanitizationMixin, serializers.Serializer):
    """Serializer for business profile updates"""
    
    # Business Information
    business_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    business_type = serializers.ChoiceField(
        choices=BUSINESS_TYPES,
        required=False,
        allow_null=True
    )
    business_type_other = serializers.CharField(max_length=100, required=False, allow_blank=True)
    business_description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    
    # Location
    business_address = serializers.CharField(max_length=200, required=False, allow_blank=True)
    business_barangay = serializers.CharField(max_length=100, required=False, allow_blank=True)
    business_city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    business_province = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_business_barangay(self, value):
        return _validate_location_name(value, 'Business Barangay')

    def validate_business_city(self, value):
        return _validate_location_name(value, 'Business City')

    def validate_business_province(self, value):
        return _validate_location_name(value, 'Business Province')
    
    # Operations - canonical unit: months
    business_age_months = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Business age in months (canonical unit). Minimum 1 month."
    )
    is_registered = serializers.BooleanField(required=False)
    registration_type = serializers.ChoiceField(
        choices=['DTI', 'SEC', 'BIR', 'none'],
        required=False,
        allow_null=True
    )
    registration_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    
    # Financial
    estimated_monthly_income = serializers.FloatField(required=False, allow_null=True, min_value=0)
    income_range = serializers.ChoiceField(
        choices=INCOME_RANGES,
        required=False,
        allow_null=True
    )
    estimated_monthly_expenses = serializers.FloatField(required=False, allow_null=True, min_value=0)
    number_of_employees = serializers.IntegerField(required=False, min_value=0)
    
    def validate(self, data):
        if data.get('business_type') == 'other' and not data.get('business_type_other'):
            raise serializers.ValidationError({
                'business_type_other': 'Please specify the business type'
            })
        return data


class AlternativeDataSerializer(InputSanitizationMixin, serializers.Serializer):
    """Serializer for alternative credit data updates"""
    
    # Education & Employment
    education_level = serializers.ChoiceField(
        choices=EDUCATION_LEVELS,
        required=False,
        allow_null=True
    )
    employment_status = serializers.ChoiceField(
        choices=['employed', 'self_employed', 'unemployed', 'retired', 'student'],
        required=False,
        allow_null=True
    )
    years_of_experience = serializers.FloatField(required=False, allow_null=True, min_value=0)
    
    # Housing
    housing_status = serializers.ChoiceField(
        choices=['owned', 'rented', 'living_with_family', 'company_provided'],
        required=False,
        allow_null=True
    )
    years_at_current_address = serializers.FloatField(required=False, allow_null=True, min_value=0)
    monthly_rent = serializers.FloatField(required=False, allow_null=True, min_value=0)
    
    # Dependents
    number_of_dependents = serializers.IntegerField(required=False, min_value=0)
    household_income = serializers.FloatField(required=False, allow_null=True, min_value=0)
    
    # Existing Credit
    has_existing_loans = serializers.BooleanField(required=False)
    existing_loan_amount = serializers.FloatField(required=False, allow_null=True, min_value=0)
    existing_loan_source = serializers.ChoiceField(
        choices=['bank', 'cooperative', 'microfinance', 'informal', 'family', 'none'],
        required=False,
        allow_null=True
    )
    loan_payment_history = serializers.ChoiceField(
        choices=['on_time', 'sometimes_late', 'often_late', 'defaulted', 'no_history'],
        required=False,
        allow_null=True
    )
    
    # Digital Footprint
    has_bank_account = serializers.BooleanField(required=False)
    bank_account_duration = serializers.FloatField(required=False, allow_null=True, min_value=0)
    has_ewallet = serializers.BooleanField(required=False)
    ewallet_usage = serializers.ChoiceField(
        choices=['daily', 'weekly', 'monthly', 'rarely', 'never'],
        required=False,
        allow_null=True
    )
    
    # Utility Payments
    pays_utilities = serializers.BooleanField(required=False)
    utility_payment_history = serializers.ChoiceField(
        choices=['on_time', 'sometimes_late', 'often_late'],
        required=False,
        allow_null=True
    )
    
    # Social Capital
    is_coop_member = serializers.BooleanField(required=False)
    community_involvement = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        max_length=10
    )
