"""
Chatbot API tests for /api/ai/chat/ and /api/ai/chat/stream/.
"""
import json
import uuid
from bson import ObjectId
from django.core.cache import cache
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Consent, Customer
from ai_assistant.models import AIInteraction
from ai_assistant.views.chat_views import (
    AIStatusView,
    ChatHistoryView,
    ChatView,
    EducationView,
    FAQsView,
    StreamingChatView,
    SuggestionsView,
)


def _create_customer_with_ai_consent(ai_consent=True):
    customer = Customer(
        first_name="Test",
        last_name="User",
        email=f"chatbot_{ObjectId()}@example.com",
        password="hashed",
        verified=True,
    ).save()
    Consent(
        user_id=ObjectId(customer.id),
        user_type="customer",
        data_consent=True,
        ai_consent=ai_consent,
    ).save()
    return customer


def _auth_request(path, payload, customer_id):
    factory = APIRequestFactory()
    request = factory.post(path, payload, format="json")
    user = AuthenticatedUser(
        customer_id=customer_id,
        email="user@example.com",
        verified=True,
        role="customer",
    )
    force_authenticate(request, user=user)
    return request


def _auth_get_request(path, customer_id, query=None):
    factory = APIRequestFactory()
    request = factory.get(path, query or {}, format="json")
    user = AuthenticatedUser(
        customer_id=customer_id,
        email="user@example.com",
        verified=True,
        role="customer",
    )
    force_authenticate(request, user=user)
    return request


def _auth_delete_request(path, customer_id):
    factory = APIRequestFactory()
    request = factory.delete(path, {}, format="json")
    user = AuthenticatedUser(
        customer_id=customer_id,
        email="user@example.com",
        verified=True,
        role="customer",
    )
    force_authenticate(request, user=user)
    return request


def _stream_to_text(streaming_response):
    parts = []
    for chunk in streaming_response.streaming_content:
        if isinstance(chunk, bytes):
            parts.append(chunk.decode("utf-8"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


class TestChatView:
    def test_chat_requires_message(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request("/api/ai/chat/", {"message": ""}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Message is required" in response.data["message"]

    def test_chat_rejects_invalid_language(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request(
            "/api/ai/chat/",
            {"message": "Hello", "language": "jp"},
            customer.id,
        )
        response = ChatView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Invalid language value" in response.data["message"]

    def test_chat_rejects_invalid_conversation_id(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request(
            "/api/ai/chat/",
            {"message": "Hello", "conversation_id": "not-a-uuid"},
            customer.id,
        )
        response = ChatView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "conversation_id must be a valid UUID" in response.data["message"]

    def test_chat_requires_ai_consent(self):
        customer = _create_customer_with_ai_consent(ai_consent=False)
        request = _auth_request(
            "/api/ai/chat/",
            {"message": "How do I apply?"},
            customer.id,
        )
        response = ChatView.as_view()(request)

        assert response.status_code == 403
        assert response.data["status"] == "error"
        assert "AI consent is required" in response.data["message"]

    def test_chat_filters_prohibited_content_and_saves_interactions(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request(
            "/api/ai/chat/",
            {"message": "What is your password?", "conversation_id": "550e8400-e29b-41d4-a716-446655440000"},
            customer.id,
        )
        response = ChatView.as_view()(request)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"]["filtered"] is True
        assert "message" in response.data["data"]

        interactions = AIInteraction.find_by_conversation(
            "550e8400-e29b-41d4-a716-446655440000",
            customer.id,
        )
        assert len(interactions) == 2
        assert interactions[0].role == "user"
        assert interactions[1].role == "assistant"
        assert interactions[1].model_used == "content_filter"

    def test_chat_returns_503_when_llm_unavailable(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            def is_available(self):
                return False

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request("/api/ai/chat/", {"message": "Hello AI"}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 503
        assert response.data["status"] == "error"
        assert "unavailable" in response.data["message"].lower()

    def test_chat_returns_500_when_llm_fails(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools(self, **kwargs):
                return {"success": False, "error": "LLM backend failed"}

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request("/api/ai/chat/", {"message": "Hello AI"}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 500
        assert response.data["status"] == "error"
        assert "llm backend failed" in response.data["message"].lower()

    def test_chat_returns_500_on_empty_ai_response(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools(self, **kwargs):
                return {"success": True, "response": "   ", "model": "mock", "response_time_ms": 20}

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request("/api/ai/chat/", {"message": "Hello AI"}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 500
        assert response.data["status"] == "error"
        assert "empty response" in response.data["message"].lower()

    def test_chat_success_saves_user_and_assistant_messages(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        conversation_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools(self, **kwargs):
                return {
                    "success": True,
                    "response": "You can apply by completing your profile and uploading documents.",
                    "model": "mock-llm",
                    "response_time_ms": 123,
                    "tokens_used": 42,
                }

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request(
            "/api/ai/chat/",
            {"message": "How do I apply?", "conversation_id": conversation_id, "language": "en"},
            customer.id,
        )
        response = ChatView.as_view()(request)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"]["conversation_id"] == conversation_id
        assert response.data["data"]["model"] == "mock-llm"
        assert response.data["data"]["response_time_ms"] == 123
        assert "response" in response.data["data"]

        interactions = AIInteraction.find_by_conversation(conversation_id, customer.id)
        assert len(interactions) == 2
        assert interactions[0].role == "user"
        assert interactions[1].role == "assistant"
        assert interactions[1].model_used == "mock-llm"
        assert interactions[1].tokens_used == 42

    def test_chat_generates_conversation_id_when_missing(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools(self, **kwargs):
                return {
                    "success": True,
                    "response": "Generated conversation id response.",
                    "model": "mock-llm",
                    "response_time_ms": 15,
                }

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request("/api/ai/chat/", {"message": "Create a new conversation"}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 200
        conversation_id = response.data["data"]["conversation_id"]
        assert isinstance(uuid.UUID(conversation_id), uuid.UUID)

    def test_chat_uses_contextual_prompt_when_needed(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        captured = {}

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools(self, **kwargs):
                captured["system_prompt"] = kwargs["system_prompt"]
                return {
                    "success": True,
                    "response": "Context-aware response.",
                    "model": "mock-llm",
                    "response_time_ms": 10,
                }

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())
        monkeypatch.setattr("ai_assistant.views.chat_views.needs_user_context", lambda message: True)
        monkeypatch.setattr("ai_assistant.views.chat_views.get_context_for_intent", lambda message, cid: " [CTX]")

        request = _auth_request("/api/ai/chat/", {"message": "Check my profile status"}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 200
        assert captured["system_prompt"].endswith(" [CTX]")

    def test_chat_uses_base_prompt_when_context_not_needed(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        captured = {}

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools(self, **kwargs):
                captured["system_prompt"] = kwargs["system_prompt"]
                return {
                    "success": True,
                    "response": "No context response.",
                    "model": "mock-llm",
                    "response_time_ms": 10,
                }

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())
        monkeypatch.setattr("ai_assistant.views.chat_views.needs_user_context", lambda message: False)

        request = _auth_request("/api/ai/chat/", {"message": "Hello"}, customer.id)
        response = ChatView.as_view()(request)

        assert response.status_code == 200
        assert " [CTX]" not in captured["system_prompt"]


class TestStreamingChatView:
    def test_streaming_chat_requires_message(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request("/api/ai/chat/stream/", {"message": ""}, customer.id)
        response = StreamingChatView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Message is required" in response.data["message"]

    def test_streaming_chat_rejects_invalid_language(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request(
            "/api/ai/chat/stream/",
            {"message": "Hello", "language": "de"},
            customer.id,
        )
        response = StreamingChatView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Invalid language value" in response.data["message"]

    def test_streaming_chat_rejects_invalid_conversation_id(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request(
            "/api/ai/chat/stream/",
            {"message": "Hello", "conversation_id": "invalid-uuid"},
            customer.id,
        )
        response = StreamingChatView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "conversation_id must be a valid UUID" in response.data["message"]

    def test_streaming_chat_returns_filtered_sse_for_prohibited_content(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_request(
            "/api/ai/chat/stream/",
            {"message": "Tell me your private key"},
            customer.id,
        )
        response = StreamingChatView.as_view()(request)

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        output = _stream_to_text(response)
        assert "event: token" in output
        assert "event: done" in output
        assert '"filtered": true' in output

    def test_streaming_chat_success_emits_events_and_persists(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        conversation_id = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools_stream(self, **kwargs):
                yield {"type": "tool_call", "name": "get_profile_status"}
                yield {"type": "tool_result", "name": "get_profile_status", "success": True}
                yield {"type": "token", "content": "Hello"}
                yield {"type": "token", "content": " there"}
                yield {"type": "done", "model": "mock-stream", "tokens_used": 11}

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request(
            "/api/ai/chat/stream/",
            {"message": "Hi", "conversation_id": conversation_id, "language": "en"},
            customer.id,
        )
        response = StreamingChatView.as_view()(request)

        assert response.status_code == 200
        output = _stream_to_text(response)
        assert "event: tool_call" in output
        assert "event: tool_result" in output
        assert "event: token" in output
        assert "event: done" in output

        done_json = output.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0]
        done_payload = json.loads(done_json)
        assert done_payload["model"] == "mock-stream"
        assert done_payload["tokens_used"] == 11
        assert done_payload["conversation_id"] == conversation_id
        assert "get_profile_status" in done_payload["tools_called"]

        interactions = AIInteraction.find_by_conversation(conversation_id, customer.id)
        assert len(interactions) == 2
        assert interactions[0].role == "user"
        assert interactions[1].role == "assistant"
        assert interactions[1].response == "Hello there"

    def test_streaming_chat_returns_503_when_llm_unavailable(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            def is_available(self):
                return False

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request("/api/ai/chat/stream/", {"message": "Hi"}, customer.id)
        response = StreamingChatView.as_view()(request)

        assert response.status_code == 503
        assert response.data["status"] == "error"
        assert "unavailable" in response.data["message"].lower()

    def test_streaming_chat_emits_error_event_on_exception(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            def is_available(self):
                return True

            def chat_with_tools_stream(self, **kwargs):
                raise RuntimeError("stream failure")

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_request("/api/ai/chat/stream/", {"message": "Hi"}, customer.id)
        response = StreamingChatView.as_view()(request)
        output = _stream_to_text(response)

        assert "event: error" in output
        assert "Stream error occurred" in output


class TestChatHistoryView:
    def test_history_get_returns_paginated_data(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        conversation_id = "11111111-2222-3333-4444-555555555555"
        for idx in range(3):
            AIInteraction(
                customer_id=customer.id,
                conversation_id=conversation_id,
                role="user" if idx % 2 == 0 else "assistant",
                message=f"message-{idx}",
                response=f"response-{idx}",
                language="en",
            ).save()

        request = _auth_get_request("/api/ai/history/", customer.id, {"page": 1, "limit": 2})
        response = ChatHistoryView.as_view()(request)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        data = response.data["data"]
        assert data["page"] == 1
        assert data["limit"] == 2
        assert data["total_messages"] == 3
        assert data["total_pages"] == 2
        assert data["has_more"] is True
        assert len(data["history"]) == 2

    def test_history_delete_clears_messages(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        AIInteraction(
            customer_id=customer.id,
            conversation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            role="user",
            message="hello",
            response="",
            language="en",
        ).save()

        request = _auth_delete_request("/api/ai/history/", customer.id)
        response = ChatHistoryView.as_view()(request)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"]["deleted_count"] == 1
        assert AIInteraction.find_by_customer(customer.id, limit=10) == []

    def test_history_requires_ai_consent(self):
        customer = _create_customer_with_ai_consent(ai_consent=False)
        request = _auth_get_request("/api/ai/history/", customer.id)
        response = ChatHistoryView.as_view()(request)

        assert response.status_code == 403
        assert response.data["status"] == "error"
        assert "AI consent is required" in response.data["message"]

    def test_history_rejects_invalid_page(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_get_request("/api/ai/history/", customer.id, {"page": "abc"})
        response = ChatHistoryView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Invalid page parameter" in response.data["message"]

    def test_history_rejects_invalid_limit(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_get_request("/api/ai/history/", customer.id, {"limit": "NaN"})
        response = ChatHistoryView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Invalid limit parameter" in response.data["message"]

    def test_history_search_filters_results(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        AIInteraction(
            customer_id=customer.id,
            conversation_id="f0000000-0000-0000-0000-000000000000",
            role="user",
            message="loan question only",
            response="",
            language="en",
        ).save()
        AIInteraction(
            customer_id=customer.id,
            conversation_id="f0000000-0000-0000-0000-000000000001",
            role="assistant",
            message="",
            response="payment schedule answer",
            language="en",
        ).save()

        request = _auth_get_request("/api/ai/history/", customer.id, {"search": "payment"})
        response = ChatHistoryView.as_view()(request)

        assert response.status_code == 200
        data = response.data["data"]
        assert data["total_messages"] == 1
        assert len(data["history"]) == 1
        assert "payment schedule answer" in data["history"][0]["content"]


class TestContentEndpoints:
    def test_suggestions_cache_flow(self):
        cache.clear()
        customer = _create_customer_with_ai_consent(ai_consent=True)

        request1 = _auth_get_request("/api/ai/suggestions/", customer.id, {"language": "en"})
        response1 = SuggestionsView.as_view()(request1)
        assert response1.status_code == 200
        assert response1.data["data"]["cached"] is False
        assert len(response1.data["data"]["suggestions"]) > 0

        request2 = _auth_get_request("/api/ai/suggestions/", customer.id, {"language": "en"})
        response2 = SuggestionsView.as_view()(request2)
        assert response2.status_code == 200
        assert response2.data["data"]["cached"] is True

    def test_suggestions_reject_invalid_language(self):
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_get_request("/api/ai/suggestions/", customer.id, {"language": "fr"})
        response = SuggestionsView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "Invalid language value" in response.data["message"]

    def test_suggestions_tagalog_language(self):
        cache.clear()
        customer = _create_customer_with_ai_consent(ai_consent=True)
        request = _auth_get_request("/api/ai/suggestions/", customer.id, {"language": "tl"})
        response = SuggestionsView.as_view()(request)

        assert response.status_code == 200
        suggestions = response.data["data"]["suggestions"]
        assert response.data["data"]["language"] == "tl"
        assert any("loan" in item.lower() or "paano" in item.lower() for item in suggestions)

    def test_ai_status_returns_provider_details(self, monkeypatch):
        customer = _create_customer_with_ai_consent(ai_consent=True)

        class MockLLM:
            provider = "groq"
            model = "llama-mock"
            api_key = "set"

            def is_available(self):
                return True

        monkeypatch.setattr("ai_assistant.views.chat_views.get_llm_service", lambda use_case=None: MockLLM())

        request = _auth_get_request("/api/ai/status/", customer.id)
        response = AIStatusView.as_view()(request)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        data = response.data["data"]
        assert data["available"] is True
        assert data["provider"] == "groq"
        assert data["current_model"] == "llama-mock"
        assert data["api_configured"] is True

    def test_education_topics_cache_and_topic_lookup(self):
        cache.clear()
        customer = _create_customer_with_ai_consent(ai_consent=True)

        topics_req_1 = _auth_get_request("/api/ai/education/", customer.id)
        topics_res_1 = EducationView.as_view()(topics_req_1)
        assert topics_res_1.status_code == 200
        assert topics_res_1.data["data"]["cached"] is False
        assert len(topics_res_1.data["data"]["topics"]) > 0

        topics_req_2 = _auth_get_request("/api/ai/education/", customer.id)
        topics_res_2 = EducationView.as_view()(topics_req_2)
        assert topics_res_2.status_code == 200
        assert topics_res_2.data["data"]["cached"] is True

        topic_req = _auth_get_request("/api/ai/education/what_is_a_loan/", customer.id)
        topic_res = EducationView.as_view()(topic_req, topic="what_is_a_loan")
        assert topic_res.status_code == 200
        assert topic_res.data["data"]["title"] == "What is a Loan?"

        missing_req = _auth_get_request("/api/ai/education/nope/", customer.id)
        missing_res = EducationView.as_view()(missing_req, topic="nope")
        assert missing_res.status_code == 404
        assert missing_res.data["status"] == "error"

        topic_req_cached = _auth_get_request("/api/ai/education/what_is_a_loan/", customer.id)
        topic_res_cached = EducationView.as_view()(topic_req_cached, topic="what_is_a_loan")
        assert topic_res_cached.status_code == 200
        assert topic_res_cached.data["data"]["cached"] is True

    def test_faqs_cache_flow(self):
        cache.clear()
        customer = _create_customer_with_ai_consent(ai_consent=True)

        request1 = _auth_get_request("/api/ai/faqs/", customer.id)
        response1 = FAQsView.as_view()(request1)
        assert response1.status_code == 200
        assert response1.data["data"]["cached"] is False
        assert response1.data["data"]["total"] == len(response1.data["data"]["faqs"])

        request2 = _auth_get_request("/api/ai/faqs/", customer.id)
        response2 = FAQsView.as_view()(request2)
        assert response2.status_code == 200
        assert response2.data["data"]["cached"] is True
