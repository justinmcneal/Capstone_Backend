import pytest
from datetime import datetime, timezone
from django.conf import settings
import mongomock

from accounts.utils.token_utils import TokenUtils
from accounts.models import RefreshTokenEntry

def test_token_utils_timezone_handling(monkeypatch):
    # Setup mongomock DB and patch settings.MONGODB
    client = mongomock.MongoClient()
    db = client['test_capstone_tokens']
    monkeypatch.setattr(settings, 'MONGODB', db)

    user_id = "6a1d12eacf50001521727621"
    email = "test@example.com"
    role = "customer"

    # Generate tokens (this should save a timezone-aware expires_at to DB)
    tokens = TokenUtils.generate_tokens(
        user_id=user_id,
        email=email,
        verified=True,
        role=role,
        token_type="remember_me"
    )

    refresh_token = tokens["refresh"]
    assert refresh_token is not None

    # Fetch the stored entry directly from DB to verify it has a timezone-aware expires_at
    entry_doc = db["refresh_tokens"].find_one({"customer": user_id})
    assert entry_doc is not None
    assert entry_doc["expires_at"] is not None

    # Verify that validating the refresh token succeeds and does not throw a TypeError
    # (specifically checking for: "TypeError: can't compare offset-naive and offset-aware datetimes")
    is_valid = TokenUtils.is_refresh_token_valid(
        customer_id=user_id,
        token=refresh_token,
        role=role
    )
    assert is_valid is True

    # Test blacklisting the token
    assert TokenUtils.is_token_blacklisted(refresh_token) is False
    TokenUtils.blacklist_token(refresh_token)
    assert TokenUtils.is_token_blacklisted(refresh_token) is True

    # After blacklist, validation should be False
    is_valid_after_blacklist = TokenUtils.is_refresh_token_valid(
        customer_id=user_id,
        token=refresh_token,
        role=role
    )
    assert is_valid_after_blacklist is False
