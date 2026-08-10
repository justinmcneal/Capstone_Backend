"""Stage 5 bounded document listing and safe-search coverage."""

from datetime import datetime, timezone

from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Customer
from documents.models import Document
from documents.views import DocumentListView


def _customer(first_name="Customer", last_name="Listing"):
    return Customer(
        first_name=first_name,
        last_name=last_name,
        email=f"customer-{ObjectId()}@example.test",
        password="hashed",
        verified=True,
    ).save()


def _admin():
    return Admin(
        username=f"admin-{ObjectId()}",
        email=f"admin-{ObjectId()}@example.test",
        password="hashed",
        active=True,
    ).save()


def _auth(actor, role):
    return AuthenticatedUser(
        customer_id=actor.id,
        email=actor.email,
        verified=True,
        role=role,
    )


def _document(customer, *, document_type="valid_id", uploaded_at=None, **kwargs):
    return Document(
        customer_id=customer.id,
        document_type=document_type,
        original_filename=kwargs.pop("original_filename", "private-name.jpg"),
        file_path=f"documents/{customer.id}/{document_type}/{ObjectId()}.jpg",
        file_size=1024,
        mime_type="image/jpeg",
        uploaded_at=uploaded_at or datetime.now(timezone.utc),
        **kwargs,
    ).save()


def _get(user, query=None):
    request = APIRequestFactory().get("/api/documents/", query or {})
    force_authenticate(request, user=user)
    return DocumentListView.as_view(authentication_classes=[])(request)


def test_customer_list_uses_database_pagination_and_stable_tie_breaker(
    monkeypatch,
):
    customer = _customer()
    timestamp = datetime(2026, 8, 10, tzinfo=timezone.utc)
    documents = [_document(customer, uploaded_at=timestamp) for _ in range(5)]
    expected_ids = [document.id for document in reversed(documents)]

    monkeypatch.setattr(
        Document,
        "find",
        classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("list endpoint must not materialize Document.find")
            )
        ),
    )
    monkeypatch.setattr(
        Document,
        "find_by_customer",
        classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("list endpoint must use database pagination")
            )
        ),
    )
    user = _auth(customer, "customer")

    first = _get(user, {"page": 1, "page_size": 2})
    second = _get(user, {"page": 2, "page_size": 2})
    beyond = _get(user, {"page": 4, "page_size": 2})

    assert first.status_code == 200
    assert first.data["data"]["total"] == 5
    assert first.data["data"]["total_pages"] == 3
    assert [item["id"] for item in first.data["data"]["documents"]] == expected_ids[:2]
    assert [item["id"] for item in second.data["data"]["documents"]] == expected_ids[2:4]
    assert beyond.data["data"]["documents"] == []
    assert beyond.data["data"]["total"] == 5


def test_empty_page_contract_and_page_size_boundaries():
    customer = _customer()
    user = _auth(customer, "customer")

    empty = _get(user)
    too_large = _get(user, {"page_size": 201})

    assert empty.status_code == 200
    assert empty.data["data"] == {
        "documents": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
        "total_pages": 0,
    }
    assert too_large.status_code == 400
    assert "between 1 and 200" in too_large.data["errors"]["page_size"]


def test_deletion_workflow_records_are_excluded_before_counting():
    customer = _customer()
    visible = _document(customer)
    _document(customer, storage_state="delete_pending")
    _document(customer, storage_state="delete_failed")

    response = _get(_auth(customer, "customer"))

    assert response.status_code == 200
    assert response.data["data"]["total"] == 1
    assert [item["id"] for item in response.data["data"]["documents"]] == [
        visible.id
    ]


def test_search_accepts_indexed_exact_values_and_rejects_filename_search():
    customer = _customer()
    valid_id = _document(customer, document_type="valid_id")
    _document(
        customer,
        document_type="proof_of_address",
        original_filename="find-me-by-filename.jpg",
    )
    user = _auth(customer, "customer")

    by_type = _get(user, {"search": "Valid ID"})
    by_document_id = _get(user, {"search": valid_id.id})
    by_customer_id = _get(user, {"search": customer.id})
    unsafe_filename = _get(user, {"search": "find-me-by-filename.jpg"})

    assert [item["id"] for item in by_type.data["data"]["documents"]] == [
        valid_id.id
    ]
    assert [item["id"] for item in by_document_id.data["data"]["documents"]] == [
        valid_id.id
    ]
    assert by_customer_id.data["data"]["total"] == 2
    assert unsafe_filename.status_code == 400
    assert "exact document type" in unsafe_filename.data["errors"]["search"]


def test_admin_page_bulk_resolves_customer_names_once(monkeypatch):
    first_customer = _customer("Alpha", "Owner")
    second_customer = _customer("Beta", "Owner")
    _document(first_customer)
    _document(second_customer)
    calls = {"count": 0}

    from documents.services.listing import bulk_customer_display_names as resolve

    def counted(customer_ids):
        calls["count"] += 1
        return resolve(customer_ids)

    monkeypatch.setattr(
        "documents.views.document_views.bulk_customer_display_names", counted
    )
    monkeypatch.setattr(
        "documents.services.notification.get_customer_by_identifier",
        lambda customer_id: (_ for _ in ()).throw(
            AssertionError("list serializer must not query customers per row")
        ),
    )

    response = _get(_auth(_admin(), "admin"), {"page_size": 20})

    assert response.status_code == 200
    assert calls["count"] == 1
    assert {item["customer_name"] for item in response.data["data"]["documents"]} == {
        "Alpha Owner",
        "Beta Owner",
    }


def test_document_indexes_cover_bounded_listing_paths(settings):
    Document.create_indexes()
    indexes = settings.MONGODB[Document.collection_name].index_information()
    key_patterns = {tuple(index["key"]) for index in indexes.values()}

    assert (
        ("customer_id", 1),
        ("storage_state", 1),
        ("uploaded_at", -1),
        ("_id", -1),
    ) in key_patterns
    assert (
        ("document_type", 1),
        ("status", 1),
        ("storage_state", 1),
        ("uploaded_at", -1),
        ("_id", -1),
    ) in key_patterns
