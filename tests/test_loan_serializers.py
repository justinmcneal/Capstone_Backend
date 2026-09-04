"""
Loan serializer validation tests.

Coverage:
- LoanProductSerializer: min <= max validation, required fields
- LoanApplicationSerializer: amount/term against product limits
- PreQualifyRequestSerializer: valid scope, required fields
- LoanReviewSerializer: action vs required fields validation
- MissingDocumentsRequestSerializer: non-empty list validation
- ApplicationInternalNoteSerializer: max length validation
"""


from loans.serializers import (
    ApplicationInternalNoteSerializer,
    LoanApplicationSerializer,
    LoanProductSerializer,
    LoanReviewSerializer,
    MissingDocumentsRequestSerializer,
    PreQualifyRequestSerializer,
)


class TestLoanProductSerializer:
    def test_valid_data(self):
        data = {
            "name": "Micro Loan",
            "code": "ML001",
            "description": "For small businesses",
            "min_amount": 5000,
            "max_amount": 50000,
            "interest_rate": 0.015,
            "min_term_months": 3,
            "max_term_months": 24,
            "required_documents": ["valid_id"],
            "min_business_months": 6,
            "min_monthly_income": 5000,
            "business_types": [],
            "target_description": "",
        }
        serializer = LoanProductSerializer(data=data)
        assert serializer.is_valid()

    def test_min_amount_exceeds_max_amount(self):
        data = {
            "name": "Bad Product",
            "code": "BP001",
            "min_amount": 50000,
            "max_amount": 5000,
            "interest_rate": 0.015,
            "min_term_months": 3,
            "max_term_months": 24,
        }
        serializer = LoanProductSerializer(data=data)
        assert not serializer.is_valid()
        assert "max_amount" in serializer.errors

    def test_missing_required_fields(self):
        data = {}
        serializer = LoanProductSerializer(data=data)
        assert not serializer.is_valid()
        assert "name" in serializer.errors


class TestLoanApplicationSerializer:
    def test_valid_data(self):
        data = {
            "product_id": "prod123",
            "requested_amount": 20000,
            "term_months": 12,
            "purpose": "Working capital",
            "preferred_disbursement_method": "cash",
        }
        serializer = LoanApplicationSerializer(data=data)
        assert serializer.is_valid()

    def test_missing_product_id(self):
        data = {
            "requested_amount": 20000,
            "term_months": 12,
        }
        serializer = LoanApplicationSerializer(data=data)
        assert not serializer.is_valid()
        assert "product_id" in serializer.errors


class TestPreQualifyRequestSerializer:
    def test_valid_data(self):
        data = {
            "product_id": "prod123",
            "amount": 20000,
            "term_months": 12,
            "purpose": "Working capital",
            "requirements_scope": "product",
        }
        serializer = PreQualifyRequestSerializer(data=data)
        assert serializer.is_valid()

    def test_invalid_requirements_scope(self):
        data = {
            "product_id": "prod123",
            "amount": 20000,
            "term_months": 12,
            "requirements_scope": "invalid_scope",
        }
        serializer = PreQualifyRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert "requirements_scope" in serializer.errors


class TestLoanReviewSerializer:
    def test_approve_with_amount(self):
        data = {
            "action": "approve",
            "approved_amount": 20000,
        }
        serializer = LoanReviewSerializer(data=data)
        assert serializer.is_valid()

    def test_reject_without_reason_fails(self):
        data = {
            "action": "reject",
        }
        serializer = LoanReviewSerializer(data=data)
        assert not serializer.is_valid()
        assert "rejection_reason" in serializer.errors

    def test_approve_without_amount_fails(self):
        data = {
            "action": "approve",
        }
        serializer = LoanReviewSerializer(data=data)
        assert not serializer.is_valid()
        assert "approved_amount" in serializer.errors


class TestMissingDocumentsRequestSerializer:
    def test_valid_request(self):
        data = {
            "missing_documents": ["valid_id", "income_proof"],
            "reason": "Please upload your ID and income proof.",
        }
        serializer = MissingDocumentsRequestSerializer(data=data)
        assert serializer.is_valid()

    def test_empty_documents_list_fails(self):
        data = {
            "missing_documents": [],
            "reason": "Some reason",
        }
        serializer = MissingDocumentsRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert "missing_documents" in serializer.errors


class TestApplicationInternalNoteSerializer:
    def test_valid_note(self):
        data = {"note": "This application looks good."}
        serializer = ApplicationInternalNoteSerializer(data=data)
        assert serializer.is_valid()

    def test_empty_note_fails(self):
        data = {"note": ""}
        serializer = ApplicationInternalNoteSerializer(data=data)
        assert not serializer.is_valid()
        assert "note" in serializer.errors

    def test_note_too_long_fails(self):
        data = {"note": "x" * 1001}
        serializer = ApplicationInternalNoteSerializer(data=data)
        assert not serializer.is_valid()
        assert "note" in serializer.errors
