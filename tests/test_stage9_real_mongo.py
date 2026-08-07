"""Real-Mongo coverage for auth-critical indexes and concurrent uniqueness."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.conf import settings
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from accounts.models import Customer
from accounts.models.activity import ActiveSession
from accounts.models.tokens import RefreshTokenEntry
from accounts.services.otp_service import OTPService
from accounts.services.password_service import PasswordService

REAL_MONGO_URI = os.getenv("REAL_MONGO_TEST_URI")


@pytest.fixture
def real_mongo_database():
    if not REAL_MONGO_URI:
        pytest.skip("REAL_MONGO_TEST_URI is not configured")

    client = MongoClient(REAL_MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    database_name = f"stage9_auth_{uuid.uuid4().hex}"
    database = client[database_name]
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


@pytest.mark.real_mongo
def test_real_mongo_auth_indexes_enforce_uniqueness(real_mongo_database, monkeypatch):
    database = real_mongo_database
    monkeypatch.setattr(settings, "MONGODB", database)

    Customer.create_indexes()
    ActiveSession.create_indexes()
    RefreshTokenEntry.create_indexes()

    customer_indexes = database["customer"].index_information()
    session_indexes = database["active_sessions"].index_information()
    refresh_indexes = database["refresh_tokens"].index_information()

    assert customer_indexes["email_1"]["unique"] is True
    assert "password_reset_delivery_reconciliation" in customer_indexes
    assert session_indexes["session_id_1"]["unique"] is True
    assert refresh_indexes["session_id_1"]["unique"] is True


@pytest.mark.real_mongo
def test_real_mongo_concurrent_customer_email_claim_has_one_winner(
    real_mongo_database,
):
    collection = real_mongo_database["customer"]
    collection.create_index("email", unique=True)
    email = f"stage9-{uuid.uuid4().hex}@example.com"

    def insert_candidate(candidate_number):
        try:
            collection.insert_one(
                {
                    "email": email,
                    "candidate_number": candidate_number,
                }
            )
            return "inserted"
        except DuplicateKeyError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(insert_candidate, range(8)))

    assert outcomes.count("inserted") == 1
    assert outcomes.count("duplicate") == 7
    assert collection.count_documents({"email": email}) == 1


@pytest.mark.real_mongo
def test_real_mongo_concurrent_session_claim_has_one_winner(real_mongo_database):
    collection = real_mongo_database["active_sessions"]
    collection.create_index("session_id", unique=True, sparse=True)
    session_id = str(uuid.uuid4())

    def insert_candidate(candidate_number):
        try:
            collection.insert_one(
                {
                    "user_id": f"customer-{candidate_number}",
                    "role": "customer",
                    "session_id": session_id,
                    "is_active": True,
                }
            )
            return "inserted"
        except DuplicateKeyError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(insert_candidate, range(8)))

    assert outcomes.count("inserted") == 1
    assert outcomes.count("duplicate") == 7
    assert collection.count_documents({"session_id": session_id}) == 1


@pytest.mark.real_mongo
def test_real_mongo_concurrent_otp_consumption_has_one_winner(
    real_mongo_database, monkeypatch
):
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    customer = Customer(
        first_name="OTP",
        last_name="Concurrency",
        email=f"otp-{uuid.uuid4().hex}@example.com",
        verified=False,
    )
    customer.set_password("OldPass123!")
    otp = OTPService.set_otp(customer)
    customer.save()

    candidates = [Customer.find_one({"_id": customer._id}) for _ in range(8)]

    def consume(candidate):
        return OTPService.consume_otp(
            candidate,
            otp,
            "verification_token",
            "verification_token_expires",
            success_updates={"verified": True},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(consume, candidates))

    stored = Customer.find_one({"_id": customer._id})
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert stored.verified is True
    assert stored.verification_token is None


@pytest.mark.real_mongo
def test_real_mongo_concurrent_password_reset_issuance_has_one_winner(
    real_mongo_database, monkeypatch
):
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    monkeypatch.setattr(
        "accounts.services.password_service.queue_password_reset_delivery",
        lambda **_kwargs: True,
    )
    customer = Customer(
        first_name="Reset",
        last_name="Concurrency",
        email=f"reset-{uuid.uuid4().hex}@example.com",
        verified=True,
    )
    customer.set_password("OldPass123!")
    customer.save()

    def issue(_candidate_number):
        return PasswordService.initiate_password_reset(customer.email)[0]

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(issue, range(8)))

    stored = Customer.find_one({"_id": customer._id})
    assert outcomes == [True] * 8
    assert stored.password_reset_issue_count == 1
    assert stored.password_reset_otp is not None
