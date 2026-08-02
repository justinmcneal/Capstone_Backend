"""Canonical loan-product bounds used by serializers and application flows."""


class ProductRuleViolation(ValueError):
    """A requested amount or term falls outside the selected product."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def validate_product_bounds(data, product=None):
    """Validate a complete or partial product definition and return field errors."""
    minimum_amount = data.get(
        "min_amount", getattr(product, "min_amount", 0) if product else 0
    )
    maximum_amount = data.get(
        "max_amount", getattr(product, "max_amount", 0) if product else 0
    )
    minimum_term = data.get(
        "min_term_months",
        getattr(product, "min_term_months", 0) if product else 0,
    )
    maximum_term = data.get(
        "max_term_months",
        getattr(product, "max_term_months", 0) if product else 0,
    )
    errors = {}
    if minimum_amount > maximum_amount:
        errors["max_amount"] = (
            "Maximum amount must be greater than or equal to minimum amount"
        )
    if minimum_term > maximum_term:
        errors["max_term_months"] = (
            "Maximum term must be greater than or equal to minimum term"
        )
    return errors


def validate_application_terms(product, requested_amount, term_months):
    """Apply the selected product's canonical amount and term constraints."""
    if requested_amount < product.min_amount or requested_amount > product.max_amount:
        raise ProductRuleViolation(
            "requested_amount",
            (
                f"Amount must be between ₱{product.min_amount:,.0f} and "
                f"₱{product.max_amount:,.0f}"
            ),
        )
    if term_months < product.min_term_months or term_months > product.max_term_months:
        raise ProductRuleViolation(
            "term_months",
            (
                f"Term must be between {product.min_term_months} and "
                f"{product.max_term_months} months"
            ),
        )
    return float(requested_amount), int(term_months)


def normalized_recommendation(product, requested_amount, qualification):
    """Return a safe recommendation bounded by the product and customer request."""
    eligible = bool(
        qualification.get("can_apply", qualification.get("eligible", False))
    )
    if not eligible:
        return 0.0
    try:
        recommendation = float(qualification.get("recommended_amount", 0) or 0)
    except (TypeError, ValueError):
        recommendation = 0.0
    lower_bound = float(product.min_amount or 0)
    upper_bound = min(float(product.max_amount or 0), float(requested_amount))
    if upper_bound < lower_bound:
        upper_bound = lower_bound
    return max(lower_bound, min(recommendation, upper_bound))
