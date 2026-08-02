"""Exact peso/centavo conversion helpers for persisted loan accounting."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CENTAVOS_PER_PESO = 100
CENTAVO = Decimal("0.01")


def to_decimal(value, field_name="amount"):
    """Convert a numeric input without inheriting binary-float artifacts."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a valid number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid number") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be a finite number")
    return result


def to_centavos(value, field_name="amount"):
    """Round a peso value half-up and return its exact integer centavos."""
    decimal_value = to_decimal(value, field_name).quantize(
        CENTAVO, rounding=ROUND_HALF_UP
    )
    return int(decimal_value * CENTAVOS_PER_PESO)


def from_centavos(value):
    """Return a two-decimal peso float for existing JSON/API contracts."""
    return float(
        (Decimal(int(value)) / CENTAVOS_PER_PESO).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )
    )


def rate_amount_centavos(principal_centavos, rate):
    """Calculate an exact, half-up centavo amount from a decimal rate."""
    amount = Decimal(int(principal_centavos)) * to_decimal(rate, "interest_rate")
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
