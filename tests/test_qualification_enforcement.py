"""
Stage 6 — Qualification enforcement tests.

Each test isolates a specific hard product requirement as the **sole**
reason for failure.  All other requirements (documents, profiles, etc.)
are fully satisfied so the test cannot pass due to a *different*
coincidental failure.

Coverage:
- Hard-fail insufficient business age (sole reason)
- Hard-fail insufficient income (sole reason)
- Both income and business age fail simultaneously
- Boundary: exactly at minimum business age passes
- Boundary: exactly at minimum income passes
- Zero business age with positive minimum fails
- Zero income with positive minimum fails
- No business profile with positive minimums fails
- AI cannot override income hard-fail
- AI cannot override business-age hard-fail
- Zero-minimum product requirements skip hard check
- Rule-based income failure is a hard missing requirement, not just a score concern
- Rule-based business-age failure is a hard missing requirement, not just a score concern
"""

from types import SimpleNamespace

from loans.services.qualification import (
    _check_hard_product_requirements,
    _validate_and_normalize_ai_qualification,
    qualify_customer,
    rule_based_qualification,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(**overrides):
    defaults = {
        "name": "Test Product",
        "min_amount": 5000,
        "max_amount": 50000,
        "min_business_months": 6,
        "min_monthly_income": 5000,
        "required_documents": ["valid_id"],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


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


def _make_alternative():
    return SimpleNamespace(
        has_bank_account=True,
        has_ewallet=True,
        utility_payment_history="on_time",
        has_existing_loans=False,
        education_level="college",
        housing_status="owned",
        employment_status="self_employed",
    )


def _make_document(document_type="valid_id", status="approved"):
    return SimpleNamespace(
        document_type=document_type,
        status=status,
        reupload_requested=False,
    )


def _fully_qualified_data(business=None, docs=None):
    """Return customer data that passes every requirement *except*
    whatever the caller overrides via the ``business`` parameter."""
    return {
        "personal": SimpleNamespace(profile_completed=True),
        "business": business or _make_business(),
        "alternative": _make_alternative(),
        "documents": docs
        if docs is not None
        else [_make_document("valid_id", "approved")],
    }


# ---------------------------------------------------------------------------
# _check_hard_product_requirements unit tests
# ---------------------------------------------------------------------------


class TestHardProductRequirements:
    """Direct unit tests for the deterministic gate function."""

    def test_hard_fail_insufficient_business_age_alone(self):
        """Business age below minimum is the sole disqualifying factor."""
        product = _make_product(min_business_months=24, min_monthly_income=5000)
        business = _make_business(business_age_months=6, estimated_monthly_income=15000)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert len(failures) == 1
        assert "business operation" in failures[0].lower()
        assert "6 months" in failures[0]
        assert "24 months" in failures[0]

    def test_hard_fail_insufficient_income_alone(self):
        """Income below minimum is the sole disqualifying factor."""
        product = _make_product(min_business_months=6, min_monthly_income=20000)
        business = _make_business(
            business_age_months=24, estimated_monthly_income=10000
        )
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert len(failures) == 1
        assert "monthly income" in failures[0].lower()

    def test_hard_fail_both_income_and_business_age(self):
        """Both requirements fail simultaneously; both messages present."""
        product = _make_product(min_business_months=24, min_monthly_income=20000)
        business = _make_business(business_age_months=6, estimated_monthly_income=5000)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert len(failures) == 2
        texts = " ".join(failures).lower()
        assert "business operation" in texts
        assert "monthly income" in texts

    def test_passes_when_exactly_at_minimum_business_age(self):
        """Boundary: business_age_months == min_business_months passes."""
        product = _make_product(min_business_months=12)
        business = _make_business(business_age_months=12)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert failures == []

    def test_passes_when_exactly_at_minimum_income(self):
        """Boundary: estimated_monthly_income == min_monthly_income passes."""
        product = _make_product(min_monthly_income=10000)
        business = _make_business(estimated_monthly_income=10000)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert failures == []

    def test_hard_fail_zero_business_age(self):
        """business_age_months=0 with a positive minimum fails."""
        product = _make_product(min_business_months=6)
        business = _make_business(business_age_months=0)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert any("business operation" in f.lower() for f in failures)

    def test_hard_fail_zero_income(self):
        """estimated_monthly_income=0 with a positive minimum fails."""
        product = _make_product(min_monthly_income=5000)
        business = _make_business(estimated_monthly_income=0)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert any("monthly income" in f.lower() for f in failures)

    def test_hard_fail_no_business_profile(self):
        """No business profile with positive minimums fails both checks."""
        product = _make_product(min_business_months=6, min_monthly_income=5000)
        data = _fully_qualified_data(business=None)
        data["business"] = None  # Explicitly no business

        failures = _check_hard_product_requirements(data, product)

        assert len(failures) == 2

    def test_zero_minimum_requirements_skips_hard_check(self):
        """Product with zero minimums never hard-fails."""
        product = _make_product(min_business_months=0, min_monthly_income=0)
        business = _make_business(business_age_months=0, estimated_monthly_income=0)
        data = _fully_qualified_data(business=business)

        failures = _check_hard_product_requirements(data, product)

        assert failures == []


# ---------------------------------------------------------------------------
# AI override prevention
# ---------------------------------------------------------------------------


class TestAICannotOverrideHardRequirements:
    """Verify that _validate_and_normalize_ai_qualification enforces
    hard requirements even when the AI payload says eligible=True."""

    def test_hard_failure_short_circuits_before_llm_construction(self, monkeypatch):
        product = _make_product(min_monthly_income=20_000)
        data = _fully_qualified_data(
            business=_make_business(estimated_monthly_income=5_000)
        )
        monkeypatch.setattr(
            "loans.services.qualification._ai_qualification_enabled", lambda: True
        )
        monkeypatch.setattr(
            "loans.services.qualification.get_customer_data", lambda customer_id: data
        )

        def unexpected_llm(*args, **kwargs):
            raise AssertionError("LLM must not be constructed after a hard failure")

        monkeypatch.setattr(
            "loans.services.qualification.get_llm_service", unexpected_llm
        )

        result = qualify_customer(
            customer_id="customer-1",
            product=product,
            requested_amount=10_000,
            term_months=12,
            purpose="Working capital",
        )

        assert result["eligible"] is False
        assert result["ai_used"] is False
        assert any(
            "monthly income" in item.lower() for item in result["missing_requirements"]
        )

    def test_ai_cannot_override_income_hard_fail(self):
        """AI returns eligible=True, but customer fails income minimum."""
        product = _make_product(min_monthly_income=20000)
        business = _make_business(
            business_age_months=24,
            estimated_monthly_income=5000,
        )
        data = _fully_qualified_data(business=business)

        ai_payload = {
            "eligible": True,
            "eligibility_score": 85,
            "risk_category": "low",
            "recommended_amount": 30000,
            "reasoning": "AI says customer is eligible",
            "strengths": ["Good business history"],
            "concerns": [],
            "missing_requirements": [],
        }

        result = _validate_and_normalize_ai_qualification(
            payload=ai_payload,
            product=product,
            requested_amount=30000,
            required_doc_types=["valid_id"],
            scope="product",
            data=data,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        assert result["recommended_amount"] == 0.0
        assert any(
            "monthly income" in m.lower() for m in result["missing_requirements"]
        )

    def test_ai_cannot_override_business_age_hard_fail(self):
        """AI returns eligible=True, but customer fails business age minimum."""
        product = _make_product(min_business_months=24)
        business = _make_business(
            business_age_months=3,
            estimated_monthly_income=50000,
        )
        data = _fully_qualified_data(business=business)

        ai_payload = {
            "eligible": True,
            "eligibility_score": 90,
            "risk_category": "low",
            "recommended_amount": 40000,
            "reasoning": "AI says customer is eligible",
            "strengths": ["High income"],
            "concerns": [],
            "missing_requirements": [],
        }

        result = _validate_and_normalize_ai_qualification(
            payload=ai_payload,
            product=product,
            requested_amount=40000,
            required_doc_types=["valid_id"],
            scope="product",
            data=data,
        )

        assert result["eligible"] is False
        assert result["can_apply"] is False
        assert result["recommended_amount"] == 0.0
        assert any(
            "business operation" in m.lower() for m in result["missing_requirements"]
        )


# ---------------------------------------------------------------------------
# Rule-based enforcement
# ---------------------------------------------------------------------------


class TestRuleBasedHardEnforcement:
    """Verify that rule_based_qualification treats income and business-age
    failures as hard missing-requirement entries, not just score concerns."""

    def test_rule_based_income_failure_is_hard_not_score_deduction(self):
        """Income below minimum produces a missing_requirements entry even
        when the score could be high enough from other factors."""
        product = _make_product(
            min_monthly_income=20000,
            min_business_months=6,
            required_documents=["valid_id"],
        )
        business = _make_business(
            business_age_months=60,
            estimated_monthly_income=10000,
            is_registered=True,
        )
        data = _fully_qualified_data(
            business=business,
            docs=[_make_document("valid_id", "approved")],
        )

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
        assert any(
            "monthly income" in m.lower() for m in result["missing_requirements"]
        )

    def test_rule_based_business_age_failure_is_hard_not_score_deduction(self):
        """Business age below minimum produces a missing_requirements entry
        even when income and all other factors are strong."""
        product = _make_product(
            min_business_months=24,
            min_monthly_income=5000,
            required_documents=["valid_id"],
        )
        business = _make_business(
            business_age_months=6,
            estimated_monthly_income=50000,
            is_registered=True,
        )
        data = _fully_qualified_data(
            business=business,
            docs=[_make_document("valid_id", "approved")],
        )

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
        assert any(
            "business operation" in m.lower() for m in result["missing_requirements"]
        )
