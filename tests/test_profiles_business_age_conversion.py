from profiles.models.profile_models import BusinessProfile


def test_years_int_conversion():
    bp = BusinessProfile(years_in_operation=2)
    assert bp.business_age_months == 24


def test_years_float_conversion():
    bp = BusinessProfile(years_in_operation=2.5)
    assert bp.business_age_months == 30


def test_canonical_months_used():
    bp = BusinessProfile(business_age_months=6)
    assert bp.business_age_months == 6


def test_invalid_years_stored_raw():
    bp = BusinessProfile(years_in_operation="unknown")
    assert bp.business_age_months == "unknown"


def test_none_results_in_none():
    bp = BusinessProfile()
    assert bp.business_age_months is None
