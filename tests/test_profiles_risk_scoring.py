"""
Risk scoring service tests.

Tests cover rule-based scoring dimensions, thresholds, and edge cases.
"""

import pytest

from profiles.services.risk_scoring import (
    _digital_score,
    _financial_score,
    _housing_score,
    _payment_behavior_score,
    _social_capital_score,
    calculate_risk_score,
)


class FakeAlternativeData:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestFinancialScore:
    def test_high_income_scores_high(self):
        alt = FakeAlternativeData(
            household_income="above_100000",
            has_existing_loans=False,
        )
        score = _financial_score(alt)
        assert score == pytest.approx(90.0, abs=0.1)

    def test_low_income_with_defaulted_loans_scores_low(self):
        alt = FakeAlternativeData(
            household_income="below_10000",
            has_existing_loans=True,
            loan_payment_history="defaulted",
        )
        score = _financial_score(alt)
        assert score == pytest.approx(10.0, abs=0.1)

    def test_missing_income_defaults_to_mid(self):
        alt = FakeAlternativeData(
            household_income=None,
            has_existing_loans=False,
        )
        score = _financial_score(alt)
        assert score == pytest.approx(65.0, abs=0.1)


class TestPaymentBehaviorScore:
    def test_on_time_payments_score_high(self):
        alt = FakeAlternativeData(
            loan_payment_history="on_time",
            utility_payment_history="on_time",
        )
        score = _payment_behavior_score(alt)
        assert score == 100.0

    def test_late_payments_score_low(self):
        alt = FakeAlternativeData(
            loan_payment_history="late",
            utility_payment_history="late",
        )
        score = _payment_behavior_score(alt)
        assert score == 40.0

    def test_missing_history_defaults_to_mid(self):
        alt = FakeAlternativeData(
            loan_payment_history=None,
            utility_payment_history=None,
        )
        score = _payment_behavior_score(alt)
        assert score == 50.0


class TestSocialCapitalScore:
    def test_coop_member_with_involvement_scores_high(self):
        alt = FakeAlternativeData(
            is_coop_member=True,
            community_involvement=["cleanup", "youth"],
        )
        score = _social_capital_score(alt)
        assert score == 100.0

    def test_no_social_capital_scores_low(self):
        alt = FakeAlternativeData(
            is_coop_member=False,
            community_involvement=None,
        )
        score = _social_capital_score(alt)
        assert score == 40.0


class TestHousingScore:
    def test_owned_long_term_no_rent_scores_high(self):
        alt = FakeAlternativeData(
            housing_status="owned",
            years_at_current_address=6,
            monthly_rent=None,
            household_income="above_100000",
        )
        score = _housing_score(alt)
        assert score == pytest.approx(83.33, abs=0.1)

    def test_rented_short_term_high_burden_scores_low(self):
        alt = FakeAlternativeData(
            housing_status="rented",
            years_at_current_address=0.5,
            monthly_rent=25000,
            household_income="30000_50000",
        )
        score = _housing_score(alt)
        assert score == pytest.approx(33.33, abs=0.1)

    def test_missing_data_defaults_to_mid(self):
        alt = FakeAlternativeData(
            housing_status=None,
            years_at_current_address=None,
            monthly_rent=None,
            household_income=None,
        )
        score = _housing_score(alt)
        assert score == pytest.approx(36.67, abs=0.1)


class TestDigitalScore:
    def test_full_digital_footprint_scores_high(self):
        alt = FakeAlternativeData(
            has_bank_account=True,
            bank_account_duration=4,
            has_ewallet=True,
            ewallet_usage="daily",
        )
        score = _digital_score(alt)
        assert score == pytest.approx(82.5, abs=0.1)

    def test_no_digital_footprint_scores_low(self):
        alt = FakeAlternativeData(
            has_bank_account=False,
            bank_account_duration=None,
            has_ewallet=False,
            ewallet_usage=None,
        )
        score = _digital_score(alt)
        assert score == pytest.approx(5.0, abs=0.1)

    def test_bank_only_no_ewallet(self):
        alt = FakeAlternativeData(
            has_bank_account=True,
            bank_account_duration=2,
            has_ewallet=False,
            ewallet_usage=None,
        )
        score = _digital_score(alt)
        assert score == pytest.approx((80 + 70 + 0 + 0) / 4, abs=0.1)


class TestRiskScoreIntegration:
    def test_low_risk_customer(self):
        alt = FakeAlternativeData(
            household_income="above_100000",
            has_existing_loans=False,
            loan_payment_history="on_time",
            utility_payment_history="on_time",
            is_coop_member=True,
            community_involvement=["org"],
            housing_status="owned",
            years_at_current_address=5,
            monthly_rent=None,
            has_bank_account=True,
            bank_account_duration=4,
            has_ewallet=True,
            ewallet_usage="daily",
        )
        result = calculate_risk_score(alt)
        assert result["category"] == "low"
        assert result["total_score"] >= 70

    def test_high_risk_customer(self):
        alt = FakeAlternativeData(
            household_income="below_10000",
            has_existing_loans=True,
            loan_payment_history="defaulted",
            utility_payment_history="late",
            is_coop_member=False,
            community_involvement=[],
            housing_status="rented",
            years_at_current_address=0.5,
            monthly_rent=25000,
            has_bank_account=False,
            bank_account_duration=None,
            has_ewallet=False,
            ewallet_usage=None,
        )
        result = calculate_risk_score(alt)
        assert result["category"] == "high"
        assert result["total_score"] < 40

    def test_middle_risk_boundary(self):
        alt = FakeAlternativeData(
            household_income="30000_50000",
            has_existing_loans=True,
            loan_payment_history="late",
            utility_payment_history="on_time",
            is_coop_member=False,
            community_involvement=[],
            housing_status="rented",
            years_at_current_address=2,
            monthly_rent=10000,
            has_bank_account=True,
            bank_account_duration=1,
            has_ewallet=True,
            ewallet_usage="monthly",
        )
        result = calculate_risk_score(alt)
        assert result["category"] in {"medium", "low"}
        assert 40 <= result["total_score"] <= 100

    def test_score_is_zero_to_hundred(self):
        alt = FakeAlternativeData()
        result = calculate_risk_score(alt)
        assert 0 <= result["total_score"] <= 100
