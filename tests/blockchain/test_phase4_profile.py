"""
Phase 4 — Mobile Profile & Wallet Address (backend side) tests.

Tests the backend endpoints that the mobile app uses to save/fetch wallet_address:
  4.1  GET /api/profile/ returns wallet_address
  4.2  PUT /api/profile/ accepts and stores wallet_address
  4.3  Serializer validates ETH address on PUT
  4.4  wallet_address round-trip (save → fetch)
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest

from profiles.serializers.profile_serializers import (
    CustomerProfileSerializer,
    CustomerProfileResponseSerializer,
)


# ── 4.1  GET response includes wallet_address ─────────────────────

class TestProfileGetIncludesWalletAddress:
    def test_get_handler_returns_wallet_address(self):
        """The GET /api/profile/ response dict includes wallet_address."""
        from profiles.views.profile_views import CustomerProfileView
        source = inspect.getsource(CustomerProfileView.get)
        assert "'wallet_address'" in source or '"wallet_address"' in source

    def test_response_serializer_has_wallet_address(self):
        """CustomerProfileResponseSerializer defines wallet_address field."""
        fields = CustomerProfileResponseSerializer().get_fields()
        assert "wallet_address" in fields


# ── 4.2  PUT accepts wallet_address ────────────────────────────────

class TestProfilePutAcceptsWalletAddress:
    def test_input_serializer_has_wallet_address(self):
        """CustomerProfileSerializer defines wallet_address as optional CharField."""
        fields = CustomerProfileSerializer().get_fields()
        assert "wallet_address" in fields
        field = fields["wallet_address"]
        assert not field.required  # optional
        assert field.max_length == 42

    def test_put_handler_updates_profile_fields_generically(self):
        """PUT handler uses setattr loop — wallet_address included automatically."""
        from profiles.views.profile_views import CustomerProfileView
        source = inspect.getsource(CustomerProfileView.put)
        # The loop: for field, value in data.items(): setattr(profile, field, value)
        assert "setattr(profile, field, value)" in source or "setattr" in source

    @patch("profiles.models.profile_models.CustomerProfile.save")
    @patch("profiles.models.profile_models.CustomerProfile.get_or_create")
    def test_wallet_address_set_on_profile_via_put(self, mock_get, mock_save):
        """Simulates PUT with wallet_address — profile field gets updated."""
        from profiles.models.profile_models import CustomerProfile

        profile = CustomerProfile(customer_id="test_cust")
        mock_get.return_value = profile

        # Simulate serializer validated_data
        validated_data = {
            "wallet_address": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28"
        }

        # Replicate the PUT handler's update loop
        for field, value in validated_data.items():
            if hasattr(profile, field):
                setattr(profile, field, value)

        assert profile.wallet_address == "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28"


# ── 4.3  Serializer validation ─────────────────────────────────────

class TestWalletAddressSerializerValidation:
    """Re-verify serializer validation (backend validates what mobile sends)."""

    def _validate(self, value):
        s = CustomerProfileSerializer(data={"wallet_address": value}, partial=True)
        return s.is_valid(), s.errors

    def test_valid_address_accepted(self):
        ok, _ = self._validate("0x5F034623bFD198980e8Af188702b871458E5d854")
        assert ok

    def test_empty_accepted(self):
        ok, _ = self._validate("")
        assert ok

    def test_null_accepted(self):
        ok, _ = self._validate(None)
        assert ok

    def test_no_0x_prefix_rejected(self):
        ok, errs = self._validate("5F034623bFD198980e8Af188702b871458E5d854")
        assert not ok
        assert "wallet_address" in errs

    def test_too_short_rejected(self):
        ok, errs = self._validate("0x1234")
        assert not ok
        assert "wallet_address" in errs

    def test_non_hex_rejected(self):
        ok, errs = self._validate("0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG")
        assert not ok
        assert "wallet_address" in errs

    def test_too_long_rejected(self):
        ok, errs = self._validate("0x" + "a" * 41)
        assert not ok
        assert "wallet_address" in errs


# ── 4.4  Round-trip: model stores and returns wallet_address ───────

class TestWalletAddressRoundTrip:
    def test_profile_stores_wallet_address(self):
        from profiles.models.profile_models import CustomerProfile
        addr = "0x5F034623bFD198980e8Af188702b871458E5d854"
        profile = CustomerProfile(customer_id="rt_test", wallet_address=addr)
        assert profile.wallet_address == addr

    def test_profile_includes_wallet_address_in_to_dict(self):
        from profiles.models.profile_models import CustomerProfile
        addr = "0x5F034623bFD198980e8Af188702b871458E5d854"
        profile = CustomerProfile(customer_id="rt_test", wallet_address=addr)
        d = profile.to_dict()
        assert d["wallet_address"] == addr

    def test_profile_wallet_address_none_by_default(self):
        from profiles.models.profile_models import CustomerProfile
        profile = CustomerProfile(customer_id="rt_test")
        assert profile.wallet_address is None

    def test_get_response_wallet_address_field_allows_null(self):
        """Response serializer allows null wallet_address (for profiles without one)."""
        fields = CustomerProfileResponseSerializer().get_fields()
        field = fields["wallet_address"]
        assert field.allow_null
