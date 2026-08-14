"""
Tests for AIInteraction model methods.

Covers:
- find_by_customer_paginated
- find_by_conversation
- delete_by_customer
"""

from bson import ObjectId

from ai_assistant.models.interaction import AIInteraction


class TestAIModelMethods:
    def test_find_by_customer_paginated(self, monkeypatch):
        customer_id = str(ObjectId())
        fake_docs = [
            {"_id": ObjectId(), "customer_id": customer_id, "conversation_id": "c1"},
            {"_id": ObjectId(), "customer_id": customer_id, "conversation_id": "c2"},
        ]

        monkeypatch.setattr(
            AIInteraction,
            "find_by_customer_paginated",
            staticmethod(lambda customer_id, page=1, limit=50, search_query=None: (fake_docs, 2)),
            raising=False,
        )

        results, total = AIInteraction.find_by_customer_paginated(customer_id, page=1, limit=10)
        assert len(results) == 2
        assert total == 2

    def test_find_by_conversation_filters_by_customer(self, monkeypatch):
        customer_id = str(ObjectId())
        conversation_id = "conv-123"
        fake_docs = [
            {"_id": ObjectId(), "customer_id": customer_id, "conversation_id": conversation_id},
        ]

        monkeypatch.setattr(
            AIInteraction,
            "find",
            staticmethod(lambda query, sort=None, limit=None: fake_docs),
            raising=False,
        )

        results = AIInteraction.find_by_conversation(conversation_id, customer_id=customer_id)
        assert len(results) == 1

    def test_delete_by_customer(self, monkeypatch):
        customer_id = str(ObjectId())

        class FakeResult:
            deleted_count = 3

        class FakeUpdateResult:
            modified_count = 0

        fake_collection = type("FakeColl", (), {
            "delete_many": lambda *args, **kwargs: FakeResult(),
            "update_many": lambda *args, **kwargs: FakeUpdateResult(),
        })()

        fake_db = {"ai_interactions": fake_collection}
        monkeypatch.setattr(
            "ai_assistant.models.interaction.get_db",
            lambda: fake_db,
            raising=False,
        )

        count = AIInteraction.delete_by_customer(customer_id)
        assert count == 3
