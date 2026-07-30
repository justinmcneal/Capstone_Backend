"""
Risk scoring service for AlternativeData.

Calculates a risk_score (0-100) and risk_category (low/medium/high)
using a weighted multi-factor rule engine. No external dependencies required.
"""

import logging
from typing import Any

logger = logging.getLogger("profiles")


class RiskScoreBreakdown:
    def __init__(self):
        self.dimensions: dict[str, dict[str, Any]] = {}
        self.total_score: float = 0.0
        self.category: str | None = None
        self.notes: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "total_score": self.total_score,
            "category": self.category,
            "notes": self.notes,
        }


def _score_dimension(name: str, value: float) -> dict[str, Any]:
    return {"score": round(min(max(value, 0.0), 100.0), 2), "name": name}


def _income_score(alternative) -> float:
    income_map = {
        "above_100000": 100,
        "50000_100000": 80,
        "30000_50000": 60,
        "20000_30000": 40,
        "10000_20000": 20,
        "below_10000": 10,
    }
    value = getattr(alternative, "household_income", None)
    return income_map.get(value, 50.0) if value is not None else 50.0


def _loan_history_score(alternative) -> float:
    history = getattr(alternative, "loan_payment_history", None)
    if not getattr(alternative, "has_existing_loans", False):
        return 80.0
    if history == "on_time":
        return 60.0
    if history == "late":
        return 30.0
    if history == "defaulted":
        return 10.0
    return 40.0


def _financial_score(alternative) -> float:
    income = _income_score(alternative)
    loan_history = _loan_history_score(alternative)
    return round((income + loan_history) / 2, 2)


def _payment_behavior_score(alternative) -> float:
    loan_history = getattr(alternative, "loan_payment_history", None)
    utility_history = getattr(alternative, "utility_payment_history", None)

    loan_map = {"on_time": 100, "late": 40, "defaulted": 0}
    utility_map = {"on_time": 100, "late": 40}

    loan_score = loan_map.get(loan_history, 50.0) if loan_history is not None else 50.0
    utility_score = (
        utility_map.get(utility_history, 50.0)
        if utility_history is not None
        else 50.0
    )

    return round((loan_score + utility_score) / 2, 2)


def _social_capital_score(alternative) -> float:
    coop = 80.0 if getattr(alternative, "is_coop_member", False) else 40.0
    involvement = getattr(alternative, "community_involvement", None)
    community = 20.0 if involvement else 0.0
    return round(min(coop + community, 100.0), 2)


def _housing_score(alternative) -> float:
    status = getattr(alternative, "housing_status", None)
    years = getattr(alternative, "years_at_current_address", None)
    rent = getattr(alternative, "monthly_rent", None)
    income = getattr(alternative, "household_income", None)

    status_map = {"owned": 100, "living_with_family": 60, "rented": 50}
    status_score = status_map.get(status, 30.0) if status is not None else 30.0

    if years is None:
        years_score = 30.0
    elif years >= 5:
        years_score = 100.0
    elif years >= 3:
        years_score = 70.0
    elif years >= 1:
        years_score = 50.0
    else:
        years_score = 20.0

    rent_score = 50.0
    if rent is not None and income:
        income_numeric_map = {
            "above_100000": 100000,
            "50000_100000": 75000,
            "30000_50000": 40000,
            "20000_30000": 25000,
            "10000_20000": 15000,
            "below_10000": 5000,
        }
        income_value = income_numeric_map.get(income)
        if income_value and income_value > 0:
            burden = (rent / income_value) * 100
            if burden < 30:
                rent_score = 100.0
            elif burden <= 50:
                rent_score = 60.0
            else:
                rent_score = 30.0

    return round((status_score + years_score + rent_score) / 3, 2)


def _digital_score(alternative) -> float:
    bank = getattr(alternative, "has_bank_account", False)
    bank_duration = getattr(alternative, "bank_account_duration", None)
    ewallet = getattr(alternative, "has_ewallet", False)
    ewallet_usage = getattr(alternative, "ewallet_usage", None)

    bank_score = 80.0 if bank else 20.0
    if bank_duration is None:
        duration_score = 50.0 if bank else 0.0
    elif bank_duration > 3:
        duration_score = 100.0
    elif bank_duration >= 1:
        duration_score = 70.0
    else:
        duration_score = 40.0

    ewallet_score = 50.0 if ewallet else 0.0
    usage_map = {"daily": 100, "weekly": 80, "monthly": 60, "rarely": 30}
    usage_score = usage_map.get(ewallet_usage, 30.0) if ewallet else 0.0

    return round(
        (bank_score + duration_score + ewallet_score + usage_score) / 4, 2
    )


def calculate_risk_score(alternative) -> dict[str, Any]:
    """Calculate risk score for an AlternativeData instance.

    Returns a dict with:
        score: float 0-100
        category: "low" | "medium" | "high"
        breakdown: dict of dimension scores and notes
    """
    breakdown = RiskScoreBreakdown()

    financial = _financial_score(alternative)
    payment = _payment_behavior_score(alternative)
    social = _social_capital_score(alternative)
    housing = _housing_score(alternative)
    digital = _digital_score(alternative)

    breakdown.dimensions = {
        "financial_stability": _score_dimension("financial_stability", financial),
        "payment_behavior": _score_dimension("payment_behavior", payment),
        "social_capital": _score_dimension("social_capital", social),
        "housing_stability": _score_dimension("housing_stability", housing),
        "digital_footprint": _score_dimension("digital_footprint", digital),
    }

    weights = {
        "financial_stability": 0.25,
        "payment_behavior": 0.20,
        "social_capital": 0.15,
        "housing_stability": 0.25,
        "digital_footprint": 0.15,
    }

    total = round(
        sum(breakdown.dimensions[k]["score"] * w for k, w in weights.items()), 2
    )
    breakdown.total_score = total

    if total >= 70:
        breakdown.category = "low"
    elif total >= 40:
        breakdown.category = "medium"
    else:
        breakdown.category = "high"

    return breakdown.to_dict()
