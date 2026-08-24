"""
Rule-based qualification fallback tests.

Coverage:
- Eligible applicant with all requirements met
- Ineligible due to insufficient business age
- Ineligible due to low income
- Ineligible due to missing documents
- Ineligible due to missing business profile
- Score clamping (never below 0 or above 100)
- Risk category derivation (low/medium/high)
- Recommended amount calculation (capped by product and requested amount)
- Alternative data bonuses
- Document type aliases and canonicalization
- Baseline vs product scope
- Explicit empty product documents means no required docs
- Consistency with AI qualification schema
"""

from types import SimpleNamespace

import pytest

from loans.services.qualification import (
    check_required_documents,
    rule_based_qualification,
)


def _make_product(**overrides):
    defaults = {
        "name": "Test Product",
        "min_amount": 5000,
        "max_amount": 50000,
        "min_business_months": 6,
        "min_monthly_income": 5000,
        "required_documents": ["valid_id", "proof_of_income"],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_data(business=None, alternative=None, docs=None):
    return {
        "personal": SimpleNamespace(profile_completed=True),
        "business": business,
        "alternative": alternative,
        "documents": docs or [],
    }


def _make_business(
    business_age_months=12,
    estimated_monthly_income=10000,
    is_registered=True,
    income_range="medium",
    business_type="retail",
):
    return SimpleNamespace(
        business_age_months=business_age_months,
        estimated_monthly_income=estimated_monthly_income,
        is_registered=is_registered,
        income_range=income_range,
        business_type=business_type,
    )


def _make_alternative(
    has_bank_account=True,
    has_ewallet=True,
    utility_payment_history="on_time",
    has_existing_loans=False,
    education_level="college",
    housing_status="owned",
    employment_status="self_employed",
):
    return SimpleNamespace(
        has_bank_account=has_bank_account,
        has_ewallet=has_ewallet,
        utility_payment_history=utility_payment_history,
        has_existing_loans=has_existing_loans,
        education_level=education_level,
        housing_status=housing_status,
        employment_status=employment_status,
    )


def _make_document(document_type="valid_id", status="approved"):
    return SimpleNamespace(
        document_type=document_type,
        status=status,
        reupload_requested=False,
    )


class TestRequiredDocumentGate:
    def test_pending_required_document_is_accepted_for_application_submission(
        self, monkeypatch
    ):
        product = _make_product(required_documents=["valid_id"])
        pending_document = _make_document("valid_id", "pending")
        monkeypatch.setattr(
            "loans.services.qualification.get_customer_data",
            lambda customer_id: _make_data(docs=[pending_document]),
        )

        result = check_required_documents(
            "customer-1",
            product,
            require_approved_documents=False,
        )

        assert result["requirements_met"] is True
        assert result["missing_requirements"] == []

    def test_missing_required_document_blocks_application_submission(
        self, monkeypatch
    ):
        product = _make_product(required_documents=["valid_id"])
        monkeypatch.setattr(
            "loans.services.qualification.get_customer_data",
            lambda customer_id: _make_data(docs=[]),
        )

        result = check_required_documents(
            "customer-1",
            product,
            require_approved_documents=False,
        )

        assert result["requirements_met"] is False
        assert result["missing_requirements"] == [
            "Document required: Valid Government ID"
        ]

    @pytest.mark.parametrize("document_status", ["rejected", "expired"])
    def test_unusable_required_document_blocks_application_submission(
        self, monkeypatch, document_status
    ):
        product = _make_product(required_documents=["valid_id"])
        unusable_document = _make_document("valid_id", document_status)
        monkeypatch.setattr(
            "loans.services.qualification.get_customer_data",
            lambda customer_id: _make_data(docs=[unusable_document]),
        )

        result = check_required_documents(
            "customer-1",
            product,
            require_approved_documents=False,
        )

        assert result["requirements_met"] is False
        assert result["missing_requirements"]

    def test_pending_required_document_blocks_loan_approval(self, monkeypatch):
        product = _make_product(required_documents=["valid_id"])
        pending_document = _make_document("valid_id", "pending")
        monkeypatch.setattr(
            "loans.services.qualification.get_customer_data",
            lambda customer_id: _make_data(docs=[pending_document]),
        )

        result = check_required_documents(
            "customer-1",
            product,
            require_approved_documents=True,
        )

        assert result["requirements_met"] is False
        assert result["missing_requirements"] == [
            "Document pending verification: Valid Government ID"
        ]


class TestRuleBasedQualification:
    def test_eligible_with_all_requirements_met(self):
        product = _make_product()
        business = _make_business(
            business_age_months=12,
            estimated_monthly_income=15000,
            is_registered=True,
        )
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved"), _make_document("proof_of_income", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is True
        assert result["can_apply"] is True
        assert result["ai_used"] is False
        assert result["eligibility_score"] >= 50
        assert result["risk_category"] in {"low", "medium", "high"}
        assert result["recommended_amount"] > 0
        assert "reasoning" in result
        assert "Rule-based assessment" in result["reasoning"]

    def test_ineligible_insufficient_business_age(self):
        product = _make_product(min_business_months=24)
        business = _make_business(business_age_months=6)
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        assert result["recommended_amount"] == 0
        assert any("business" in str(c).lower() for c in result["concerns"] + result["missing_requirements"])

    def test_ineligible_low_income(self):
        product = _make_product(min_monthly_income=20000)
        business = _make_business(
            business_age_months=24,
            estimated_monthly_income=10000,
        )
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        assert any("income" in str(c).lower() or "Income" in str(c) for c in result["concerns"] + result["missing_requirements"])

    def test_ineligible_missing_documents(self):
        product = _make_product(required_documents=["valid_id", "proof_of_income", "business_permit"])
        business = _make_business()
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        missing_labels = [str(m) for m in result["missing_requirements"]]
        assert any("Proof of Income" in m or "Business Permit" in m for m in missing_labels)

    def test_ineligible_no_business_profile(self):
        product = _make_product()
        data = _make_data(business=None, alternative=_make_alternative(), docs=[])

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        assert any("Business profile" in str(m) for m in result["missing_requirements"])

    def test_score_clamping_never_exceeds_bounds(self):
        product = _make_product(
            min_business_months=999,
            min_monthly_income=999999,
            required_documents=["valid_id", "proof_of_income", "business_permit", "proof_of_address"],
        )
        business = _make_business(
            business_age_months=0,
            estimated_monthly_income=0,
            is_registered=False,
        )
        alternative = _make_alternative(
            has_bank_account=False,
            has_ewallet=False,
            utility_payment_history="poor",
        )
        docs = []
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=500000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert 0 <= result["eligibility_score"] <= 100

    def test_risk_category_low(self):
        product = _make_product()
        business = _make_business(
            business_age_months=60,
            estimated_monthly_income=50000,
            is_registered=True,
        )
        alternative = _make_alternative()
        docs = [
            _make_document("valid_id", "approved"),
            _make_document("proof_of_income", "approved"),
        ]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["risk_category"] == "low"

    def test_risk_category_medium(self):
        product = _make_product(min_business_months=12, min_monthly_income=10000)
        business = _make_business(
            business_age_months=5,
            estimated_monthly_income=15000,
            is_registered=False,
        )
        alternative = _make_alternative(has_bank_account=False, has_ewallet=False)
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=10000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["risk_category"] in {"medium", "high"}

    def test_risk_category_high(self):
        product = _make_product()
        business = _make_business(
            business_age_months=3,
            estimated_monthly_income=3000,
            is_registered=False,
        )
        alternative = _make_alternative(
            has_bank_account=False,
            has_ewallet=False,
            utility_payment_history="poor",
        )
        docs = []
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=50000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["risk_category"] == "high"

    def test_recommended_amount_capped_by_product_max(self):
        product = _make_product(min_amount=5000, max_amount=20000)
        business = _make_business(
            business_age_months=24,
            estimated_monthly_income=100000,
        )
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=50000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["recommended_amount"] <= product.max_amount

    def test_recommended_amount_capped_by_requested(self):
        product = _make_product(min_amount=5000, max_amount=100000)
        business = _make_business(
            business_age_months=24,
            estimated_monthly_income=10000,
        )
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=15000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["recommended_amount"] <= 15000

    def test_recommended_amount_zero_when_ineligible(self):
        product = _make_product(min_business_months=999)
        business = _make_business(business_age_months=1)
        alternative = _make_alternative()
        docs = []
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["recommended_amount"] == 0

    def test_alternative_data_bonuses(self):
        product = _make_product()
        business = _make_business(
            business_age_months=12,
            estimated_monthly_income=10000,
        )
        alternative = _make_alternative(
            has_bank_account=True,
            has_ewallet=True,
            utility_payment_history="on_time",
        )
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert any("bank account" in str(s).lower() for s in result["strengths"])
        assert any("digital" in str(s).lower() for s in result["strengths"])
        assert any("payment history" in str(s).lower() for s in result["strengths"])

    def test_document_type_alias_resolution(self):
        product = _make_product(required_documents=["income_proof"])
        business = _make_business()
        alternative = _make_alternative()
        docs = [_make_document("proof_of_income", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is True
        assert result["can_apply"] is True
        assert len(result["missing_requirements"]) == 0

    def test_baseline_scope_uses_default_documents(self):
        product = _make_product(required_documents=[])
        business = _make_business()
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="baseline",
            require_approved_documents=True,
        )

        assert result["eligible"] is True
        assert result["can_apply"] is True

    def test_explicit_empty_product_docs_means_no_requirements(self):
        product = _make_product(required_documents=[])
        business = _make_business()
        alternative = _make_alternative()
        docs = []
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is True
        assert result["can_apply"] is True
        assert len(result["missing_requirements"]) == 0

    def test_schema_matches_ai_qualification_output(self):
        product = _make_product()
        business = _make_business()
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        required_fields = {
            "eligible",
            "eligibility_score",
            "risk_category",
            "recommended_amount",
            "reasoning",
            "strengths",
            "concerns",
            "missing_requirements",
            "can_apply",
            "ai_used",
            "required_documents_resolved",
            "requirements_scope",
        }
        assert set(result.keys()) == required_fields
        assert result["ai_used"] is False
        assert isinstance(result["strengths"], list)
        assert isinstance(result["concerns"], list)
        assert isinstance(result["missing_requirements"], list)

    def test_document_not_approved_counts_as_missing(self):
        product = _make_product(required_documents=["valid_id"])
        business = _make_business()
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "pending")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        assert any("valid_id" in str(m).lower() or "Valid Government ID" in str(m) for m in result["missing_requirements"])

    def test_business_registration_bonus(self):
        product = _make_product()
        business = _make_business(
            business_age_months=12,
            estimated_monthly_income=10000,
            is_registered=True,
        )
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
        )

        assert any("registered" in str(s).lower() for s in result["strengths"])

    def test_custom_reason_message(self):
        product = _make_product()
        business = _make_business()
        alternative = _make_alternative()
        docs = [_make_document("valid_id", "approved")]
        data = _make_data(business=business, alternative=alternative, docs=docs)

        result = rule_based_qualification(
            data,
            product,
            requested_amount=20000,
            requirements_scope="product",
            require_approved_documents=True,
            reason="Custom fallback reason",
        )

        assert result["reasoning"] == "Custom fallback reason"
