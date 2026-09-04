"""Canonical release-scope and accounting policy for Loans settlement."""

from django.conf import settings

LOAN_SETTLEMENT_POLICY_VERSION = "cash-check-wallet-v1"
LOAN_ACCOUNTING_POLICY_VERSION = "scheduled-balance-v1"
MANUAL_SETTLEMENT_METHODS = frozenset({"cash", "check"})
WALLET_METHOD = "wallet"


class SettlementRailUnavailable(ValueError):
    """Raised when a syntactically valid rail is outside the release scope."""

    code = "SETTLEMENT_RAIL_UNAVAILABLE"


def available_disbursement_methods():
    methods = ["cash", "check"]
    if getattr(settings, "BLOCKCHAIN_ENABLED", False):
        methods.append(WALLET_METHOD)
    return tuple(methods)


def available_customer_payment_methods():
    methods = ["office_cash", "office_check"]
    if getattr(settings, "BLOCKCHAIN_ENABLED", False):
        methods.append(WALLET_METHOD)
    return tuple(methods)


def require_disbursement_method(method):
    normalized = str(method or "").strip().lower()
    if normalized == WALLET_METHOD and not getattr(
        settings, "BLOCKCHAIN_ENABLED", False
    ):
        raise SettlementRailUnavailable(
            "Wallet settlement is unavailable while blockchain support is disabled"
        )
    if normalized not in MANUAL_SETTLEMENT_METHODS | {WALLET_METHOD}:
        raise ValueError("Disbursement method must be one of: cash, check, wallet")
    return normalized

def public_settlement_policy():
    """Return the client-safe, versioned release policy contract."""
    return {
        "policy_version": LOAN_SETTLEMENT_POLICY_VERSION,
        "accounting_policy_version": LOAN_ACCOUNTING_POLICY_VERSION,
        "currency": "PHP",
        "money_precision": "centavo",
        "rounding": "half_up_centavo",
        "timezone": "UTC",
        "available_disbursement_methods": list(available_disbursement_methods()),
        "available_customer_payment_methods": list(
            available_customer_payment_methods()
        ),
        "payoff_basis": "all_remaining_scheduled_principal_interest_and_penalties",
        "penalty_mode": "manual_officer_explicit_amount",
        "due_date_adjustment": "none_calendar_date",
        "wallet_rate_basis": "verification_time",
        "wallet_rate_max_age_seconds": 300,
    }
