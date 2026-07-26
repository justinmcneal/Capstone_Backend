"""
=============================================================================
AI CONTEXT BUILDER TESTS
=============================================================================

Validates privacy controls in the AI assistant context builder:
- mask_value shows only the last N characters
- Redacted fields are never exposed in AI context
- Masked fields are partially hidden
- Helper functions behave predictably
- Context selection by intent respects privacy
=============================================================================
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from ai_assistant.services.context_builder import (
    REDACTED_FIELDS,
    MASKED_FIELDS,
    mask_value,
    format_currency,
    format_date,
    days_until,
    summarize_status,
    build_profile_summary,
    build_documents_summary,
    build_loans_summary,
    build_user_context,
    build_minimal_context,
    get_context_for_intent,
)


# =============================================================================
# MOCK HELPERS
# =============================================================================

class FakeProfile:
    def __init__(self, **kwargs):
        self.completion_percentage = kwargs.get('completion_percentage', 0)
        self.profile_completed = kwargs.get('profile_completed', False)
        for field, _ in [
            ('date_of_birth', 'date of birth'),
            ('gender', 'gender'),
            ('civil_status', 'civil status'),
            ('address_line1', 'address'),
            ('barangay', 'barangay'),
            ('city_municipality', 'city / municipality'),
            ('province', 'province'),
        ]:
            setattr(self, field, kwargs.get(field, None))


class FakeBusinessProfile:
    def __init__(self, **kwargs):
        self.business_name = kwargs.get('business_name')
        self.business_type = kwargs.get('business_type')
        self.business_age_months = kwargs.get('business_age_months', 0)
        self.estimated_monthly_income = kwargs.get('estimated_monthly_income')
        self.income_range = kwargs.get('income_range')
        self.is_registered = kwargs.get('is_registered', False)
        for field, _ in [
            ('business_type', 'business type'),
            ('income_range', 'income range'),
        ]:
            setattr(self, field, kwargs.get(field, None))


class FakeAlternativeData:
    def __init__(self, **kwargs):
        self.education_level = kwargs.get('education_level')
        self.housing_status = kwargs.get('housing_status')
        self.risk_score = kwargs.get('risk_score')
        self.risk_category = kwargs.get('risk_category')


class FakeDocument:
    def __init__(self, **kwargs):
        self.document_type = kwargs.get('document_type', 'unknown')
        self.status = kwargs.get('status', 'unknown')
        self.verified = kwargs.get('verified', False)


class FakeLoanApplication:
    def __init__(self, **kwargs):
        self.status = kwargs.get('status', 'unknown')
        self.approved_amount = kwargs.get('approved_amount')
        self.requested_amount = kwargs.get('requested_amount')
        self.term_months = kwargs.get('term_months')
        self.disbursed_amount = kwargs.get('disbursed_amount')
        self.id = kwargs.get('id', 'loan_123')


class FakeRepaymentSchedule:
    def __init__(self, installments=None):
        self.installments = installments or []

    def get_remaining_balance(self):
        return 0.0

    def get_next_payment(self):
        return None


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestHelperFunctions:
    """Tests for simple helper functions."""

    def test_mask_value_short_string(self):
        """Short strings should be returned as-is."""
        assert mask_value("abc") == "abc"

    def test_mask_value_none(self):
        """None should be returned as-is."""
        assert mask_value(None) is None

    def test_mask_value_empty(self):
        """Empty string should be returned as-is."""
        assert mask_value("") == ""

    def test_mask_value_default_show_last(self):
        """Default mask should show last 4 chars."""
        assert mask_value("1234567890") == "******7890"

    def test_mask_value_custom_show_last(self):
        """Custom show_last should work."""
        assert mask_value("1234567890", show_last=2) == "********90"

    def test_format_currency_none(self):
        """None amount should return N/A."""
        assert format_currency(None) == "N/A"

    def test_format_currency_zero(self):
        """Zero should be formatted."""
        assert format_currency(0) == "₱0"

    def test_format_currency_positive(self):
        """Positive amount should be formatted with commas."""
        assert format_currency(150000) == "₱150,000"

    def test_format_date_none(self):
        """None datetime should return N/A."""
        assert format_date(None) == "N/A"

    def test_format_date_valid(self):
        """Valid datetime should be formatted."""
        dt = datetime(2026, 7, 26, 12, 0, 0)
        assert format_date(dt) == "Jul 26, 2026"

    def test_days_until_none(self):
        """None datetime should return 0."""
        assert days_until(None) == 0

    def test_days_until_future(self):
        """Future datetime should return positive days."""
        future = datetime(2030, 1, 1)
        assert days_until(future) > 0

    def test_days_until_past(self):
        """Past datetime should return negative days."""
        past = datetime(2020, 1, 1)
        assert days_until(past) < 0

    def test_summarize_status_known(self):
        """Known statuses should return user-friendly text."""
        assert summarize_status('approved') == 'Approved ✓'
        assert summarize_status('disbursed') == 'Active (disbursed)'

    def test_summarize_status_unknown(self):
        """Unknown statuses should be title-cased."""
        assert summarize_status('custom_status') == 'Custom Status'


# =============================================================================
# PRIVACY / REDACTION TESTS
# =============================================================================

class TestPrivacyControls:
    """Privacy field lists should exclude sensitive data from context."""

    def test_redacted_fields_excluded(self):
        """Passwords, OTPs, keys, and financial IDs must not appear in context summaries."""
        sensitive = ['password', 'pin', 'otp', 'secret', 'private_key', 'seed_phrase',
                     'ssn', 'tax_id', 'bank_account', 'credit_card', 'cvv']
        for field in sensitive:
            assert field in REDACTED_FIELDS, f"{field} should be in REDACTED_FIELDS"

    def test_masked_fields_partially_hidden(self):
        """PII fields should be masked rather than fully exposed."""
        pii = ['mobile_number', 'phone', 'email']
        for field in pii:
            assert field in MASKED_FIELDS, f"{field} should be in MASKED_FIELDS"

    def test_mask_value_does_not_expose_full_value(self):
        """mask_value should never return the full unmasked value."""
        original = "09171234567"
        masked = mask_value(original)
        assert original not in masked
        assert masked.endswith(original[-4:])

    def test_redacted_fields_not_in_profile_summary(self):
        """Sensitive fields should not be present in profile summary output."""
        profile = FakeProfile(
            date_of_birth='1990-01-01',
            gender='male',
            civil_status='single',
            address_line1='123 Main St',
            barangay='Sample',
            city_municipality='City',
            province='Province',
            password='secret123',
            otp='123456',
        )
        with patch('profiles.models.profile_models.CustomerProfile.find_by_customer', return_value=profile):
            result = build_profile_summary('customer_123')

        assert 'secret123' not in str(result)
        assert '123456' not in str(result)
        assert result['missing_fields'] == []


# =============================================================================
# BUILD_PROFILE_SUMMARY TESTS
# =============================================================================

class TestBuildProfileSummary:
    """Profile summary builder should correctly reflect profile state."""

    def test_empty_profile_returns_zero_completion(self):
        """Missing profile should result in zero completion and not-started state."""
        with patch('profiles.models.profile_models.CustomerProfile.find_by_customer', return_value=None):
            result = build_profile_summary('customer_123')

        assert result['completion_pct'] == 0
        assert result['has_business'] is False
        assert result['missing_fields'] == []

    def test_complete_profile_returns_full_completion(self):
        """All required fields should mark profile as complete."""
        profile = FakeProfile(
            date_of_birth='1990-01-01',
            gender='male',
            civil_status='single',
            address_line1='123 Main St',
            barangay='Sample',
            city_municipality='City',
            province='Province',
        )
        profile.completion_percentage = 100
        profile.profile_completed = True
        with patch('profiles.models.profile_models.CustomerProfile.find_by_customer', return_value=profile):
            result = build_profile_summary('customer_123')

        assert result['completion_pct'] == 100
        assert result['missing_fields'] == []

    def test_incomplete_profile_lists_missing_fields(self):
        """Missing required fields should be listed."""
        profile = FakeProfile(gender='male')
        profile.completion_percentage = 20
        with patch('profiles.models.profile_models.CustomerProfile.find_by_customer', return_value=profile):
            result = build_profile_summary('customer_123')

        assert 'date of birth' in result['missing_fields']
        assert 'address' in result['missing_fields']

    def test_business_profile_summary(self):
        """Business profile should be summarized correctly."""
        business = FakeBusinessProfile(
            business_name='My Shop',
            business_type='Retail',
            business_age_months=18,
            estimated_monthly_income=50000,
            income_range='₱20k-50k',
        )
        with patch('profiles.models.profile_models.CustomerProfile.find_by_customer', return_value=None):
            with patch('profiles.models.profile_models.BusinessProfile.find_by_customer', return_value=business):
                result = build_profile_summary('customer_123')

        assert result['has_business'] is True
        assert result['business_complete'] is True
        assert result['business_summary'] is not None
        assert 'My Shop' in result['business_summary']

    def test_alternative_data_summary(self):
        """Alternative data should be summarized correctly."""
        alternative = FakeAlternativeData(
            education_level='college',
            housing_status='owned',
            risk_category='low',
        )
        with patch('profiles.models.profile_models.CustomerProfile.find_by_customer', return_value=None):
            with patch('profiles.models.profile_models.BusinessProfile.find_by_customer', return_value=None):
                with patch('profiles.models.profile_models.AlternativeData.find_by_customer', return_value=alternative):
                    result = build_profile_summary('customer_123')

        assert result['alternative_complete'] is True
        assert result['risk_category'] == 'low'


# =============================================================================
# BUILD_DOCUMENTS_SUMMARY TESTS
# =============================================================================

class TestBuildDocumentsSummary:
    """Document summary should correctly count and categorize documents."""

    def test_no_documents_returns_empty(self):
        """No documents should return zero counts."""
        with patch('documents.models.document.Document.find_by_customer', return_value=[]):
            result = build_documents_summary('customer_123')

        assert result['total'] == 0
        assert result['verified'] == 0
        assert result['pending'] == 0
        assert result['rejected'] == 0

    def test_documents_categorized_by_status(self):
        """Documents should be counted by status."""
        docs = [
            FakeDocument(document_type='government_id', status='approved'),
            FakeDocument(document_type='proof_of_address', status='pending'),
            FakeDocument(document_type='business_permit', status='rejected'),
        ]
        with patch('documents.models.document.Document.find_by_customer', return_value=docs):
            result = build_documents_summary('customer_123')

        assert result['total'] == 3
        assert result['verified'] == 1
        assert result['pending'] == 1
        assert result['rejected'] == 1


# =============================================================================
# BUILD_LOANS_SUMMARY TESTS
# =============================================================================

class TestBuildLoansSummary:
    """Loan summary should correctly summarize applications."""

    def test_no_loans_returns_empty(self):
        """No applications should return zero counts."""
        with patch('loans.models.application.LoanApplication.find_by_customer', return_value=[]):
            result = build_loans_summary('customer_123')

        assert result['total_applications'] == 0
        assert result['active_loans'] == 0

    def test_active_loan_counted(self):
        """Disbursed loans should be counted as active."""
        apps = [
            FakeLoanApplication(status='disbursed', disbursed_amount=50000),
            FakeLoanApplication(status='approved'),
        ]
        with patch('loans.models.application.LoanApplication.find_by_customer', return_value=apps):
            with patch('loans.models.repayment.RepaymentSchedule.find_by_loan', return_value=None):
                result = build_loans_summary('customer_123')

        assert result['total_applications'] == 2
        assert result['active_loans'] == 1

    def test_outstanding_balance_formatted(self):
        """Outstanding balance should be formatted as currency string."""
        schedule = FakeRepaymentSchedule()
        schedule.get_remaining_balance = lambda: 15000
        apps = [FakeLoanApplication(status='disbursed', id='loan_1')]
        with patch('loans.models.application.LoanApplication.find_by_customer', return_value=apps):
            with patch('loans.models.repayment.RepaymentSchedule.find_by_loan', return_value=schedule):
                result = build_loans_summary('customer_123')

        assert '₱15,000' in result['total_outstanding']


# =============================================================================
# INTENT SELECTION TESTS
# =============================================================================

class TestContextIntentSelection:
    """Context builder should select appropriate detail level for different intents."""

    def test_overview_keywords_use_full_context(self):
        """Overview/summary questions should request full context."""
        result = get_context_for_intent('Give me an overview of my account', 'customer_123')
        assert '=== USER CONTEXT ===' in result

    def test_loan_keywords_use_loans_only(self):
        """Loan/payment questions should include loans only."""
        with patch('ai_assistant.services.context_builder.build_user_context') as mock_build:
            get_context_for_intent('How much do I owe?', 'customer_123')
            mock_build.assert_called_once_with('customer_123', include_profile=False, include_documents=False)

    def test_document_keywords_use_documents_only(self):
        """Document questions should include documents only."""
        with patch('ai_assistant.services.context_builder.build_user_context') as mock_build:
            get_context_for_intent('What documents have I uploaded?', 'customer_123')
            mock_build.assert_called_once_with('customer_123', include_profile=False, include_loans=False)

    def test_profile_keywords_use_profile_only(self):
        """Profile questions should include profile only."""
        with patch('ai_assistant.services.context_builder.build_user_context') as mock_build:
            get_context_for_intent('What is my profile completion?', 'customer_123')
            mock_build.assert_called_once_with('customer_123', include_documents=False, include_loans=False)

    def test_general_question_uses_minimal_context(self):
        """General questions should use minimal context."""
        with patch('ai_assistant.services.context_builder.build_minimal_context') as mock_build:
            mock_build.return_value = '[User: Profile: 50% | Docs: 2 | Loans: 0]'
            result = get_context_for_intent('Hello, how are you?', 'customer_123')
            mock_build.assert_called_once_with('customer_123')
            assert '[User:' in result
