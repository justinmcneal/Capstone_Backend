"""Real-Mongo coverage for production-critical indexes and behavior."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from django.conf import settings
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from accounts.models import Customer
from accounts.models.activity import ActiveSession
from accounts.models.tokens import RefreshTokenEntry
from accounts.services.otp_service import OTPService
from accounts.services.password_service import PasswordService
from documents.models import Document, DocumentRevisionConflict
from profiles.models import (
    CustomerProfile,
    ProfileRevisionConflict,
    RiskReviewRequest,
)

REAL_MONGO_URI = os.getenv("REAL_MONGO_TEST_URI")


@pytest.fixture
def real_mongo_database():
    if not REAL_MONGO_URI:
        pytest.skip("REAL_MONGO_TEST_URI is not configured")

    client = MongoClient(REAL_MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    # Atlas limits database names to 38 bytes on some deployments.
    database_name = f"s9_{uuid.uuid4().hex[:24]}"
    assert len(database_name.encode("utf-8")) <= 38
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
    assert session_indexes["last_active_1"]["expireAfterSeconds"] == 2592000
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


@pytest.mark.real_mongo
def test_real_mongo_atomic_profile_creation_has_one_document(
    real_mongo_database, monkeypatch
):
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    CustomerProfile.create_indexes()
    customer_id = str(uuid.uuid4())

    with ThreadPoolExecutor(max_workers=8) as executor:
        profiles = list(
            executor.map(
                lambda _candidate: CustomerProfile.get_or_create(customer_id),
                range(8),
            )
        )

    assert len({profile.id for profile in profiles}) == 1
    assert real_mongo_database["customer_profiles"].count_documents({}) == 1


@pytest.mark.real_mongo
def test_real_mongo_profile_revision_allows_one_concurrent_winner(
    real_mongo_database, monkeypatch
):
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    profile = CustomerProfile(customer_id=str(uuid.uuid4())).save()

    def update(candidate):
        try:
            profile.update_fields(
                {"nationality": f"Candidate {candidate}"},
                expected_revision=0,
            )
            return "updated"
        except ProfileRevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(update, range(8)))

    assert outcomes.count("updated") == 1
    assert outcomes.count("conflict") == 7
    stored = CustomerProfile.find_by_customer(profile.customer_id)
    assert stored.profile_revision == 1


@pytest.mark.real_mongo
def test_real_mongo_risk_review_index_enforces_one_request_per_score(
    real_mongo_database, monkeypatch
):
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    RiskReviewRequest.create_indexes()
    collection = real_mongo_database[RiskReviewRequest.collection_name]
    review_key = {
        "customer_id": str(uuid.uuid4()),
        "risk_calculated_revision": 4,
    }

    collection.insert_one({**review_key, "status": "pending"})
    with pytest.raises(DuplicateKeyError):
        collection.insert_one({**review_key, "status": "resolved"})

    indexes = collection.index_information()
    assert indexes["unique_customer_scoring_review"]["unique"] is True


@pytest.mark.real_mongo
def test_real_mongo_document_listing_is_bounded_across_scopes(
    real_mongo_database, monkeypatch
):
    """Exercise Stage 5 pagination/index behavior with a representative volume."""
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    Document.create_indexes()
    collection = real_mongo_database[Document.collection_name]
    customer_ids = [str(uuid.uuid4()) for _ in range(100)]
    collection.insert_many(
        [
            {
                "customer_id": customer_ids[index % len(customer_ids)],
                "document_type": "valid_id" if index % 2 else "proof_of_address",
                "original_filename": f"document-{index}.jpg",
                "file_path": f"documents/load/{index}.jpg",
                "file_size": 1024,
                "mime_type": "image/jpeg",
                "status": "pending",
                "verified": False,
                "revision": 0,
                "storage_state": "available",
                "uploaded_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            for index in range(5000)
        ]
    )

    customer_query = Document.available_query({"customer_id": customer_ids[0]})
    customer_page, customer_total = Document.paginate(
        customer_query, page=1, page_size=25
    )
    officer_query = Document.available_query(
        {"customer_id": {"$in": customer_ids[:10]}}
    )
    officer_page, officer_total = Document.paginate(
        officer_query, page=2, page_size=50
    )
    admin_page, admin_total = Document.paginate(
        Document.available_query({}), page=100, page_size=25
    )

    assert customer_total == 50
    assert len(customer_page) == 25
    assert officer_total == 500
    assert len(officer_page) == 50
    assert admin_total == 5000
    assert len(admin_page) == 25

    explain = real_mongo_database.command(
        "explain",
        {
            "find": Document.collection_name,
            "filter": customer_query,
            "sort": {"uploaded_at": -1, "_id": -1},
            "limit": 25,
        },
        verbosity="executionStats",
    )
    stats = explain["executionStats"]
    assert stats["nReturned"] == 25
    assert stats["totalDocsExamined"] <= customer_total


@pytest.mark.real_mongo
def test_real_mongo_document_indexes_and_concurrent_review_have_one_winner(
    real_mongo_database, monkeypatch
):
    """Prove document uniqueness and compare-and-set behavior on real MongoDB."""
    monkeypatch.setattr(settings, "MONGODB", real_mongo_database)
    Document.create_indexes()
    document = Document(
        customer_id=str(uuid.uuid4()),
        document_type="valid_id",
        original_filename="concurrency.jpg",
        file_path=f"documents/real-mongo/{uuid.uuid4().hex}.jpg",
        file_size=1024,
        mime_type="image/jpeg",
        upload_session_id=str(uuid.uuid4()),
    ).save()
    snapshots = [Document.find_by_id(document.id) for _ in range(8)]

    def approve(snapshot):
        try:
            snapshot.review(
                action="approve",
                reviewer_id=str(uuid.uuid4()),
                expected_revision=snapshot.revision,
            )
            return "approved"
        except DocumentRevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(approve, snapshots))

    assert outcomes.count("approved") == 1
    assert outcomes.count("conflict") == 7
    stored = Document.find_by_id(document.id)
    assert stored.status == "approved"
    assert stored.verified is True
    indexes = real_mongo_database[Document.collection_name].index_information()
    assert indexes["upload_session_id_1"]["unique"] is True
