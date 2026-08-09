from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.management.commands.encrypt_sensitive_fields import FIELD_MAP
from accounts.models import Customer
from config.field_encryption import (
    FieldDecryptionError,
    _build_keyring,
    _get_fernet,
    decrypt_value,
    encrypt_value,
    encrypted_value_key_id,
    is_encrypted_value,
    primary_key_id,
    reencrypt_value,
)


@pytest.fixture
def encryption_settings(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    settings.FIELD_ENCRYPTION_STRICT_DECRYPTION = True
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()
    yield settings
    _get_fernet.cache_clear()
    _build_keyring.cache_clear()


def test_versioned_encryption_round_trips_text_and_structured_values(
    encryption_settings,
):
    text_value = encrypt_value("sensitive")
    structured_value = encrypt_value({"nested": [1, "two"]})

    assert text_value.startswith("enc::v2::")
    assert structured_value.startswith("encbson::v2::")
    assert encrypted_value_key_id(text_value) == primary_key_id()
    assert decrypt_value(text_value) == "sensitive"
    assert decrypt_value(structured_value) == {"nested": [1, "two"]}


def test_previous_key_can_read_and_rotate_ciphertext(encryption_settings):
    old_key = encryption_settings.FIELD_ENCRYPTION_KEY
    old_ciphertext = encrypt_value("rotate-me")
    old_key_id = encrypted_value_key_id(old_ciphertext)
    legacy_ciphertext = "enc::" + Fernet(old_key.encode()).encrypt(
        b"legacy-rotate-me"
    ).decode()

    encryption_settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption_settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = (old_key,)

    assert decrypt_value(old_ciphertext) == "rotate-me"
    assert decrypt_value(legacy_ciphertext) == "legacy-rotate-me"
    rotated = reencrypt_value(old_ciphertext)
    rotated_legacy = reencrypt_value(legacy_ciphertext)
    assert decrypt_value(rotated) == "rotate-me"
    assert decrypt_value(rotated_legacy) == "legacy-rotate-me"
    assert encrypted_value_key_id(rotated) == primary_key_id()
    assert encrypted_value_key_id(rotated_legacy) == primary_key_id()
    assert encrypted_value_key_id(rotated) != old_key_id


def test_strict_decryption_rejects_corruption_and_missing_keys(encryption_settings):
    ciphertext = encrypt_value("do-not-return-ciphertext-as-data")
    corrupted = f"{ciphertext[:-4]}AAAA"

    with pytest.raises(FieldDecryptionError, match="failed authentication"):
        decrypt_value(corrupted)

    encryption_settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption_settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = ()
    with pytest.raises(FieldDecryptionError, match="unavailable key"):
        decrypt_value(ciphertext)


def test_customer_phone_uses_declared_field_encryption(encryption_settings):
    customer = Customer(
        first_name="Encrypted",
        last_name="Customer",
        email="encrypted-customer@example.com",
        phone="09171234567",
        verified=True,
    )
    customer.set_password("OldPass123!")
    customer.save()

    raw = encryption_settings.MONGODB[Customer.collection_name].find_one(
        {"_id": customer._id}
    )
    assert is_encrypted_value(raw["phone"])
    assert Customer.find_one({"_id": customer._id}).phone == "09171234567"


def test_encryption_command_is_dry_run_by_default_and_verifies_after_apply(
    encryption_settings,
):
    collection = encryption_settings.MONGODB[Customer.collection_name]
    result = collection.insert_one(
        {
            "email": "legacy-encryption@example.com",
            "phone": "09170000000",
            "verification_token": "123456",
        }
    )

    call_command("encrypt_sensitive_fields", stdout=StringIO())
    assert collection.find_one({"_id": result.inserted_id})["phone"] == "09170000000"

    call_command("encrypt_sensitive_fields", apply=True, stdout=StringIO())
    encrypted = collection.find_one({"_id": result.inserted_id})
    assert is_encrypted_value(encrypted["phone"])
    assert is_encrypted_value(encrypted["verification_token"])
    call_command("encrypt_sensitive_fields", verify=True, stdout=StringIO())


def test_encryption_command_rotates_previous_key_and_detects_plaintext(
    encryption_settings,
):
    old_key = encryption_settings.FIELD_ENCRYPTION_KEY
    old_ciphertext = encrypt_value("old-secret")
    collection = encryption_settings.MONGODB[Customer.collection_name]
    result = collection.insert_one(
        {"email": "rotation@example.com", "verification_token": old_ciphertext}
    )

    encryption_settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    encryption_settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = (old_key,)
    call_command("encrypt_sensitive_fields", rotate=True, apply=True, stdout=StringIO())
    rotated = collection.find_one({"_id": result.inserted_id})["verification_token"]
    assert encrypted_value_key_id(rotated) == primary_key_id()
    call_command("encrypt_sensitive_fields", verify=True, stdout=StringIO())

    collection.update_one(
        {"_id": result.inserted_id}, {"$set": {"verification_token": "plaintext"}}
    )
    with pytest.raises(CommandError, match="verification failed"):
        call_command("encrypt_sensitive_fields", verify=True, stdout=StringIO())


def test_backfill_field_map_matches_account_model_declarations():
    assert FIELD_MAP[Customer.collection_name] == Customer.encrypted_fields
    assert "phone" in FIELD_MAP[Customer.collection_name]
    assert "pending_email_otp" in FIELD_MAP[Customer.collection_name]
    assert "two_factor_recovery_otp" in FIELD_MAP[Customer.collection_name]
