"""Versioned, explainable rule-based scoring for alternative profile data."""

import logging
from typing import Any

from profiles.models import (
    EWALLET_USAGE_VALUES,
    HOUSING_STATUSES,
    LOAN_PAYMENT_HISTORIES,
    UTILITY_PAYMENT_HISTORIES,
)

logger = logging.getLogger("profiles")

RISK_SCORING_POLICY_VERSION = "2026-08-09-v1"
RISK_SCORE_USE = "informational_only"

LEGACY_INCOME_BAND_VALUES = {
    "above_100000": 100_000.0,
    "50000_100000": 75_000.0,
    "30000_50000": 40_000.0,
    "20000_30000": 25_000.0,
    "10000_20000": 15_000.0,
    "below_10000": 5_000.0,
}


class RiskScoreBreakdown:
    def __init__(self):
        self.dimensions: dict[str, dict[str, Any]] = {}
        self.total_score: float = 0.0
        self.category: str | None = None
        self.notes: list[str] = []
        self.reason_codes: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "total_score": self.total_score,
            "category": self.category,
            "notes": self.notes,
            "reason_codes": self.reason_codes,
            "policy_version": RISK_SCORING_POLICY_VERSION,
            "intended_use": RISK_SCORE_USE,
            "manual_review_required": True,
        }


def _score_dimension(
    name: str, value: float, reason_codes: list[str]
) -> dict[str, Any]:
    return {
        "score": round(min(max(value, 0.0), 100.0), 2),
        "name": name,
        "reason_codes": reason_codes,
    }


def _numeric_income(value) -> float | None:
    """Return canonical numeric PHP income, tolerating legacy stored bands."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return LEGACY_INCOME_BAND_VALUES.get(str(value))


def _income_score(alternative) -> float:
    income = _numeric_income(getattr(alternative, "household_income", None))
    if income is None:
        return 50.0
    if income >= 100_000:
        return 100.0
    if income >= 50_000:
        return 80.0
    if income >= 30_000:
        return 60.0
    if income >= 20_000:
        return 40.0
    if income >= 10_000:
        return 20.0
    return 10.0


def _loan_history_score(alternative) -> float:
    history = getattr(alternative, "loan_payment_history", None)
    if not getattr(alternative, "has_existing_loans", False):
        return 80.0
    if history not in LOAN_PAYMENT_HISTORIES:
        history = "no_history"
    return {
        "on_time": 100.0,
        "sometimes_late": 60.0,
        "often_late": 30.0,
        "defaulted": 10.0,
        "no_history": 50.0,
    }.get(history, 50.0)


def _financial_score(alternative) -> float:
    return round(
        (_income_score(alternative) + _loan_history_score(alternative)) / 2,
        2,
    )


def _payment_behavior_score(alternative) -> float:
    loan_history = getattr(alternative, "loan_payment_history", None)
    utility_history = getattr(alternative, "utility_payment_history", None)
    if loan_history not in LOAN_PAYMENT_HISTORIES:
        loan_history = "no_history"
    if utility_history not in UTILITY_PAYMENT_HISTORIES:
        utility_history = None

    loan_map = {
        "on_time": 100,
        "sometimes_late": 60,
        "often_late": 30,
        "defaulted": 0,
        "no_history": 50,
    }
    utility_map = {"on_time": 100, "sometimes_late": 60, "often_late": 30}
    loan_score = loan_map.get(loan_history, 50.0)
    utility_score = utility_map.get(utility_history, 50.0)
    return round((loan_score + utility_score) / 2, 2)


def _social_capital_score(alternative) -> float:
    coop = 80.0 if getattr(alternative, "is_coop_member", False) else 40.0
    involvement = getattr(alternative, "community_involvement", None)
    community = 20.0 if involvement else 0.0
    return round(min(coop + community, 100.0), 2)


def _housing_score(alternative) -> float:
    housing_status = getattr(alternative, "housing_status", None)
    if housing_status not in HOUSING_STATUSES:
        housing_status = None
    years = getattr(alternative, "years_at_current_address", None)
    rent = getattr(alternative, "monthly_rent", None)
    income = _numeric_income(getattr(alternative, "household_income", None))

    status_map = {
        "owned": 100,
        "company_provided": 70,
        "living_with_family": 60,
        "rented": 50,
    }
    status_score = status_map.get(housing_status, 30.0)

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
    if rent is not None and income and income > 0:
        burden = (rent / income) * 100
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
    if ewallet_usage not in EWALLET_USAGE_VALUES:
        ewallet_usage = None

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
    usage_map = {
        "daily": 100,
        "weekly": 80,
        "monthly": 60,
        "rarely": 30,
        "never": 0,
    }
    usage_score = usage_map.get(ewallet_usage, 0.0) if ewallet else 0.0
    return round(
        (bank_score + duration_score + ewallet_score + usage_score) / 4,
        2,
    )


def _income_reason(alternative) -> str:
    income = _numeric_income(getattr(alternative, "household_income", None))
    if income is None:
        return "income_missing"
    if income >= 50_000:
        return "income_high"
    if income >= 20_000:
        return "income_moderate"
    return "income_low"


def _history_reason(prefix: str, value) -> str:
    normalized = str(value or "no_history")
    allowed = {
        "on_time",
        "sometimes_late",
        "often_late",
        "defaulted",
        "no_history",
    }
    if normalized not in allowed:
        normalized = "no_history"
    return f"{prefix}_{normalized}"


def _dimension_reasons(alternative) -> dict[str, list[str]]:
    loan_reason = (
        "no_existing_loans"
        if not getattr(alternative, "has_existing_loans", False)
        else _history_reason(
            "loan_history", getattr(alternative, "loan_payment_history", None)
        )
    )
    housing = str(getattr(alternative, "housing_status", None) or "missing")
    utility = _history_reason(
        "utility_history", getattr(alternative, "utility_payment_history", None)
    )
    digital = (
        "digital_accounts_present"
        if getattr(alternative, "has_bank_account", False)
        or getattr(alternative, "has_ewallet", False)
        else "digital_accounts_absent"
    )
    social = (
        "community_participation_present"
        if getattr(alternative, "is_coop_member", False)
        or bool(getattr(alternative, "community_involvement", None))
        else "community_participation_absent"
    )
    return {
        "financial_stability": [_income_reason(alternative), loan_reason],
        "payment_behavior": [loan_reason, utility],
        "social_capital": [social],
        "housing_stability": [f"housing_{housing}"],
        "digital_footprint": [digital],
    }


def calculate_risk_score(alternative) -> dict[str, Any]:
    """Calculate a versioned informational score and non-sensitive explanation."""

    breakdown = RiskScoreBreakdown()
    reasons = _dimension_reasons(alternative)
    dimension_scores = {
        "financial_stability": _financial_score(alternative),
        "payment_behavior": _payment_behavior_score(alternative),
        "social_capital": _social_capital_score(alternative),
        "housing_stability": _housing_score(alternative),
        "digital_footprint": _digital_score(alternative),
    }
    breakdown.dimensions = {
        name: _score_dimension(name, score, reasons[name])
        for name, score in dimension_scores.items()
    }
    breakdown.reason_codes = sorted(
        {code for dimension in reasons.values() for code in dimension}
    )

    weights = {
        "financial_stability": 0.25,
        "payment_behavior": 0.20,
        "social_capital": 0.15,
        "housing_stability": 0.25,
        "digital_footprint": 0.15,
    }
    total = round(
        sum(breakdown.dimensions[name]["score"] * weight for name, weight in weights.items()),
        2,
    )
    breakdown.total_score = total

    if total >= 70:
        breakdown.category = "low"
    elif total >= 40:
        breakdown.category = "medium"
    else:
        breakdown.category = "high"

    breakdown.notes = [
        "Informational profile score only; not an approval, pricing, or adverse-action decision."
    ]
    return breakdown.to_dict()
