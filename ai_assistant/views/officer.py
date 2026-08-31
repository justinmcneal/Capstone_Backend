"""Loan-officer-only AI assistant HTTP boundaries."""

import json
import logging
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.conf import settings
from django.http import StreamingHttpResponse
from pymongo.errors import PyMongoError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import escape_llm_output, sanitize_multiline_text
from ai_assistant.metrics import (
    AI_ACTIVE_STREAMS,
    AI_PROVIDER_LATENCY,
    AI_PROVIDER_REQUESTS,
    AI_STREAM_LIMIT_CANCELLATIONS,
    AI_TOKENS,
    decrement,
    increment,
    observe,
)
from ai_assistant.serializers.officer import OfficerChatRequestSerializer
from ai_assistant.services import get_llm_service
from ai_assistant.services.idempotency import (
    claim,
    mark_complete,
    mark_failed,
    request_fingerprint,
)
from ai_assistant.services.officer_audit import (
    OfficerAIAuditUnavailable,
    record_officer_ai_access,
    record_officer_ai_result,
    record_officer_review_brief,
)
from ai_assistant.services.officer_history import sign_officer_assistant_history
from ai_assistant.services.officer_policy import validate_officer_response
from ai_assistant.services.officer_prompt import (
    OFFICER_SYSTEM_PROMPT,
    OFFICER_SUGGESTION_INTENTS,
    officer_suggestions,
)
from ai_assistant.services.officer_review_brief import (
    build_review_brief,
    build_unavailable_review_brief,
    render_review_brief,
)
from ai_assistant.services.officer_scope import (
    has_current_ai_consent,
    revalidate_officer_scope,
    resolve_officer_scope,
)
from ai_assistant.services.officer_tools import (
    OFFICER_TOOL_SCHEMAS,
    execute_officer_tool_result,
)
from ai_assistant.services.request_limits import resolve_request_id
from ai_assistant.views.chat_views import AIRequestMetricsMixin

logger = logging.getLogger("ai_assistant")

_OFFICER_TOOL_SCHEMAS = cast(list[dict[str, Any]], OFFICER_TOOL_SCHEMAS)
ALLOWED_TOOL_NAMES = frozenset(
    schema["function"]["name"] for schema in _OFFICER_TOOL_SCHEMAS
)
SAFE_CONTROLLED_ERROR_CODES = frozenset(
    {
        "AI_PROVIDER_BUSY",
        "AI_PROVIDER_CIRCUIT_OPEN",
        "AI_PROVIDER_ERROR",
        "AI_PROVIDER_STREAM_MALFORMED",
        "AI_PROVIDER_STREAM_OUTPUT_LIMIT",
        "AI_PROVIDER_STREAM_DURATION_LIMIT",
        "AI_PROVIDER_STREAM_TRUNCATED",
        "AI_PROVIDER_TIMEOUT",
        "AI_PROVIDER_UNAVAILABLE",
        "AI_OFFICER_CONSENT_CHANGED",
        "AI_OFFICER_SCOPE_CHANGED",
        "AI_OFFICER_TOOL_READ_FAILED",
        "AI_OFFICER_TOOL_UNKNOWN",
        "AI_OFFICER_TOOL_VALIDATION_FAILED",
    }
)
SAFE_METRIC_PROVIDERS = frozenset({"groq", "ollama"})
SAFE_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
MAX_SAFE_PROVIDER_TOKENS = 1_000_000
MAX_SAFE_DURATION_MS = 86_400_000
OFFICER_IDEMPOTENCY_LEASE_SECONDS = min(
    int(getattr(settings, "AI_ASSISTANT_IDEMPOTENCY_LEASE_SECONDS", 900)),
    300,
)


def _consent_required_response():
    return error_response(
        message="Current customer AI consent is required to use this feature",
        code="CONSENT_REQUIRED",
        status_code=status.HTTP_403_FORBIDDEN,
    )


def _officer_request_fingerprint(scope, data):
    scope_key = f"officer:{scope.officer_id}:{scope.application_id}"
    if data.get("intent"):
        scope_key = f"{scope_key}:intent:{data['intent']}"
    return request_fingerprint(
        data["message"],
        data["conversation_id"],
        data["language"],
        history=data.get("history", []),
        scope_key=scope_key,
    )


def _claim_officer_request(scope, request_id, data):
    return claim(
        scope.customer_id,
        request_id,
        fingerprint=_officer_request_fingerprint(scope, data),
        lease_seconds=OFFICER_IDEMPOTENCY_LEASE_SECONDS,
    )


def _officer_idempotency_response(request_claim):
    state = request_claim.get("state")
    if state == "conflict":
        return error_response(
            message="Idempotency-Key was already used for a different request",
            code="AI_IDEMPOTENCY_KEY_REUSED",
            status_code=status.HTTP_409_CONFLICT,
        )
    if state == "in_progress":
        return error_response(
            message="An identical AI request is already processing",
            code="AI_REQUEST_IN_PROGRESS",
            status_code=status.HTTP_409_CONFLICT,
        )
    if state == "complete":
        return error_response(
            message="This AI request has already completed",
            code="AI_REQUEST_ALREADY_COMPLETED",
            status_code=status.HTTP_409_CONFLICT,
        )
    return None


def _release_officer_request(scope, request_id):
    try:
        mark_failed(scope.customer_id, request_id)
    except PyMongoError:
        logger.warning(
            "Officer AI idempotency lease release failed",
            extra={"request_id": request_id},
        )


def _require_officer(request):
    allowed, actor_or_response = AccessControlMixin().require_roles(
        request, {"loan_officer"}
    )
    return None if allowed else actor_or_response


def _safe_tool_names(values):
    names = []
    if values is None:
        return names
    if not isinstance(values, (list, tuple)):
        raise ValueError("Malformed provider tool metadata")
    for value in values or []:
        name = str(value or "")
        if name in ALLOWED_TOOL_NAMES and name not in names:
            names.append(name)
    return names


def _safe_controlled_error_code(value):
    try:
        code = str(value or "").strip()
    except Exception:
        return "AI_PROVIDER_ERROR"
    return code if code in SAFE_CONTROLLED_ERROR_CODES else "AI_PROVIDER_ERROR"


def _safe_metric_provider(value):
    provider = str(value or "unknown").strip().lower()
    return provider if provider in SAFE_METRIC_PROVIDERS else "other"


def _safe_model_identifier(llm):
    model = getattr(llm, "model", "")
    if not isinstance(model, str):
        return "unknown"
    model = model.strip()
    return model if SAFE_MODEL_PATTERN.fullmatch(model) else "unknown"


def _safe_token_count(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return 0
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    if (
        not numeric.is_finite()
        or numeric != numeric.to_integral_value()
        or numeric < 0
    ):
        return 0
    return min(MAX_SAFE_PROVIDER_TOKENS, int(numeric))


def _safe_duration_ms(value, fallback):
    measured = max(0, min(MAX_SAFE_DURATION_MS, int(fallback or 0)))
    if isinstance(value, bool):
        return measured
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return measured
    if (
        not numeric.is_finite()
        or numeric < 0
        or numeric > MAX_SAFE_DURATION_MS
    ):
        return measured
    return min(MAX_SAFE_DURATION_MS, int(numeric))


def _record_provider_metrics(
    llm, *, outcome, started, operation, tokens_used=0, provider=None
):
    provider_name = _safe_metric_provider(
        provider or getattr(llm, "provider", "unknown")
    )
    increment(AI_PROVIDER_REQUESTS, provider=provider_name, outcome=outcome)
    observe(
        AI_PROVIDER_LATENCY,
        max(0, time.monotonic() - started),
        provider=provider_name,
        operation=operation,
    )
    tokens = _safe_token_count(tokens_used)
    increment(AI_TOKENS, amount=tokens, provider=provider_name)


def _bound_executor(scope, request_id, evidence=None):
    captured_request_id = request_id

    def execute(tool_name, tool_args, _customer_id, request_id=None):
        execution = execute_officer_tool_result(
            tool_name,
            tool_args,
            scope,
            request_id=request_id or captured_request_id,
        )
        if evidence is not None:
            evidence.append(
                {
                    "tool_name": tool_name,
                    "success": execution.get("success") is True,
                    **(
                        {"result": execution.get("result")}
                        if execution.get("success") is True
                        else {"code": execution.get("code")}
                    ),
                }
            )
        return execution

    return execute


def _execute_preset_intent(scope, request_id, intent, evidence):
    """Run the server-owned tool sequence for one deterministic preset."""
    tool_names = []
    execution = {"success": True}
    for tool_name in OFFICER_SUGGESTION_INTENTS[intent]:
        execution = _bound_executor(scope, request_id, evidence)(
            tool_name,
            {},
            scope.customer_id,
            request_id=request_id,
        )
        if execution.get("success") is not True:
            break
        tool_names.append(tool_name)
    return {
        "success": True,
        "code": execution.get("code"),
        "response_time_ms": 0,
        "tools_called": tool_names,
    }


def _rendered_review_brief(evidence, data):
    # A validated preset intent is the server-owned semantic request. Ignore
    # any client-edited label when building the brief so a preset cannot be
    # rerouted through free-text scope handling.
    message = "" if data.get("intent") else data["message"]
    diagnostics = []
    brief = build_review_brief(
        evidence,
        language=data["language"],
        message=message,
        diagnostics=diagnostics,
    )
    return {
        **brief,
        "narration": render_review_brief(brief),
    }, {
        "success": True,
        "provider": "deterministic",
        "model": None,
        "response_time_ms": 0,
        "tokens_used": 0,
        "diagnostic_code": diagnostics[-1] if diagnostics else None,
    }


def _is_scope_limited_request(data):
    brief = build_review_brief(
        [], language=data["language"], message=data["message"]
    )
    return brief.get("review_state") == "scope_limited"


def _authorization_error(scope):
    try:
        if not revalidate_officer_scope(scope):
            return "AI_OFFICER_SCOPE_CHANGED"
    except Exception:
        return "AI_OFFICER_SCOPE_CHANGED"
    try:
        if not has_current_ai_consent(scope):
            return "AI_OFFICER_CONSENT_CHANGED"
    except Exception:
        return "AI_OFFICER_CONSENT_CHANGED"
    return None


def _officer_provider_preflight(scope, request_id, language, started, *, stream=False):
    """Load the planner provider only for free-form officer questions."""
    try:
        llm = get_llm_service(use_case="chat")
        provider_available = llm.is_available()
    except Exception:
        _release_officer_request(scope, request_id)
        _record_provider_metrics(
            None,
            outcome="error",
            started=started,
            operation="stream" if stream else "chat",
        )
        record_officer_ai_result(
            scope,
            request_id,
            language,
            outcome="AI_PROVIDER_ERROR",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        logger.error(
            "Officer AI provider setup failed",
            extra={"request_id": request_id},
        )
        return None, error_response(
            message=(
                "Failed to process officer AI stream request"
                if stream
                else "Failed to process officer AI request"
            ),
            code="AI_PROVIDER_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if not provider_available:
        _release_officer_request(scope, request_id)
        _record_provider_metrics(
            llm,
            outcome="unavailable",
            started=started,
            operation="stream" if stream else "chat",
        )
        record_officer_ai_result(
            scope,
            request_id,
            language,
            outcome="AI_PROVIDER_UNAVAILABLE",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return None, error_response(
            message="AI service is currently unavailable",
            code="AI_PROVIDER_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return llm, None


class OfficerAIStatusView(AccessControlMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        response = _require_officer(request)
        if response is not None:
            return response
        if not getattr(settings, "AI_ASSISTANT_ENABLED", True):
            return success_response(
                data={
                    "available": False,
                    "provider": getattr(settings, "LLM_PROVIDER", "unknown"),
                    "current_model": None,
                    "api_configured": False,
                    "reachable": False,
                    "authenticated": False,
                    "model_available": False,
                    "state": "disabled",
                    "circuit": "disabled",
                    "preset_summaries_available": False,
                    "free_text_available": False,
                    "free_text_state": "disabled",
                },
                message="Officer AI status retrieved",
            )
        llm = get_llm_service(use_case="chat")
        readiness = llm.readiness() if hasattr(llm, "readiness") else {
            "available": llm.is_available(),
            "configured": bool(getattr(llm, "api_key", None)),
            "reachable": llm.is_available(),
            "authenticated": llm.is_available(),
            "model_available": llm.is_available(),
            "state": "available" if llm.is_available() else "unavailable",
            "circuit": "unknown",
        }
        available = bool(readiness["available"])
        return success_response(
            data={
                "available": available,
                "provider": llm.provider,
                "current_model": _safe_model_identifier(llm) if available else None,
                "api_configured": readiness["configured"],
                "reachable": readiness["reachable"],
                "authenticated": readiness["authenticated"],
                "model_available": readiness["model_available"],
                "state": readiness["state"],
                "circuit": readiness["circuit"],
                "preset_summaries_available": True,
                "free_text_available": available,
                "free_text_state": readiness["state"],
            },
            message="Officer AI status retrieved",
        )


class OfficerSuggestionsView(APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        role_response = _require_officer(request)
        if role_response is not None:
            return role_response
        application_id = str(request.query_params.get("application_id", "") or "")
        if not application_id:
            return error_response(
                message="application_id is required",
                errors={"application_id": "This field is required"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        language = str(request.query_params.get("language", "en") or "").lower()
        if language not in {"en", "tl"}:
            return error_response(
                message="Invalid language value",
                errors={"language": "Use one of: en, tl"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        scope, response = resolve_officer_scope(request, application_id)
        if response is not None:
            return response
        if not has_current_ai_consent(scope):
            return _consent_required_response()
        return success_response(
            data={"suggestions": officer_suggestions(language), "language": language},
            message="Officer suggestions retrieved",
        )


class OfficerChatView(AIRequestMetricsMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ChatRateThrottle,)
    metrics_endpoint = "officer_chat"

    def post(self, request):
        role_response = _require_officer(request)
        if role_response is not None:
            return role_response
        serializer = OfficerChatRequestSerializer(
            data=request.data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return error_response(
                message="Invalid officer assistant request",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        scope, response = resolve_officer_scope(
            request, serializer.validated_data["application_id"]
        )
        if response is not None:
            return response
        if not has_current_ai_consent(scope):
            return _consent_required_response()
        if not getattr(settings, "AI_ASSISTANT_ENABLED", True):
            return error_response(
                message="AI assistant is temporarily disabled",
                code="AI_ASSISTANT_DISABLED",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        data = serializer.validated_data
        request_id, validation_error = resolve_request_id(request)
        if validation_error:
            return validation_error
        request_claim = _claim_officer_request(scope, request_id, data)
        duplicate_response = _officer_idempotency_response(request_claim)
        if duplicate_response is not None:
            return duplicate_response
        try:
            record_officer_ai_access(scope, request_id, data["language"])
        except OfficerAIAuditUnavailable:
            _release_officer_request(scope, request_id)
            return error_response(
                message="AI access audit is temporarily unavailable",
                code="AI_AUDIT_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        started = time.monotonic()
        scope_limited = _is_scope_limited_request(data)
        if data.get("intent") or scope_limited:
            llm = None
        else:
            llm, preflight_error = _officer_provider_preflight(
                scope, request_id, data["language"], started
            )
            if preflight_error is not None:
                return preflight_error

        authorization_error = _authorization_error(scope)
        if authorization_error:
            _release_officer_request(scope, request_id)
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome=authorization_error,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return error_response(
                message="Officer access to this application is no longer available."
                if authorization_error == "AI_OFFICER_SCOPE_CHANGED"
                else "Customer AI consent is no longer available.",
                code=authorization_error,
                status_code=status.HTTP_403_FORBIDDEN,
            )

        evidence = []
        try:
            if data.get("intent"):
                # A deterministic preset always returns a review brief,
                # including an unavailable brief when a read-only tool cannot
                # load data. Do not turn that expected data failure into a
                # generic provider error.
                result = _execute_preset_intent(
                    scope, request_id, data["intent"], evidence
                )
            elif scope_limited:
                result = {
                    "success": True,
                    "response_time_ms": 0,
                    "tools_called": [],
                }
            else:
                result = llm.chat_with_tools(
                    message=data["message"],
                    customer_id=scope.customer_id,
                    conversation_history=data["history"],
                    language=data["language"],
                    system_prompt=OFFICER_SYSTEM_PROMPT,
                    tools=OFFICER_TOOL_SCHEMAS,
                    tool_executor=_bound_executor(scope, request_id, evidence),
                    request_id=request_id,
                    officer_mode=True,
                )
        except Exception:
            _release_officer_request(scope, request_id)
            _record_provider_metrics(
                llm,
                outcome="error",
                started=started,
                operation="chat",
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome="AI_PROVIDER_ERROR",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            logger.error(
                "Officer AI provider request failed",
                extra={"request_id": request_id},
            )
            return error_response(
                message="Failed to process officer AI request",
                code="AI_PROVIDER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if not isinstance(result, dict):
            result = {}
        raw_tool_names = result.get("tools_called")
        if raw_tool_names is not None and not isinstance(raw_tool_names, (list, tuple)):
            _release_officer_request(scope, request_id)
            _record_provider_metrics(
                llm,
                outcome="error",
                started=started,
                operation="chat",
                provider=result.get("provider"),
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome="AI_PROVIDER_ERROR",
                duration_ms=_safe_duration_ms(
                    result.get("response_time_ms"),
                    (time.monotonic() - started) * 1000,
                ),
            )
            return error_response(
                message="Failed to process officer AI request",
                code="AI_PROVIDER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        duration_ms = _safe_duration_ms(
            result.get("response_time_ms"),
            (time.monotonic() - started) * 1000,
        )
        tool_names = _safe_tool_names(result.get("tools_called"))
        if not result.get("success"):
            _release_officer_request(scope, request_id)
            outcome = _safe_controlled_error_code(result.get("code"))
            _record_provider_metrics(
                llm,
                outcome="error",
                started=started,
                operation="chat",
                provider=result.get("provider"),
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome=outcome,
                tool_names=tool_names,
                duration_ms=duration_ms,
            )
            return error_response(
                message="AI service is temporarily unavailable",
                code=outcome,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        review_brief, narration_result = _rendered_review_brief(evidence, data)
        narration = sanitize_multiline_text(
            escape_llm_output(review_brief["narration"])
        )
        review_brief["narration"] = narration
        duration_ms = _safe_duration_ms(
            (
                narration_result.get("response_time_ms")
                if isinstance(narration_result, dict)
                else None
            ),
            (time.monotonic() - started) * 1000,
        )
        authorization_error = _authorization_error(scope)
        if authorization_error:
            _release_officer_request(scope, request_id)
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome=authorization_error,
                tool_names=tool_names,
                duration_ms=duration_ms,
            )
            return error_response(
                message="Officer access to this application is no longer available."
                if authorization_error == "AI_OFFICER_SCOPE_CHANGED"
                else "Customer AI consent is no longer available.",
                code=authorization_error,
                status_code=status.HTTP_403_FORBIDDEN,
            )
        record_officer_ai_result(
            scope,
            request_id,
            data["language"],
            outcome="success",
            tool_names=tool_names,
            duration_ms=duration_ms,
            diagnostic_code=(
                narration_result.get("diagnostic_code")
                if isinstance(narration_result, dict)
                else None
            ),
        )
        try:
            record_officer_review_brief(
                scope,
                request_id,
                data["language"],
                brief={
                    key: value
                    for key, value in review_brief.items()
                    if key != "narration"
                },
            )
        except OfficerAIAuditUnavailable:
            _release_officer_request(scope, request_id)
            return error_response(
                message="AI review audit is temporarily unavailable",
                code="AI_AUDIT_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        mark_complete(scope.customer_id, request_id)
        _record_provider_metrics(
            llm,
            outcome="success",
            started=started,
            operation="chat",
            tokens_used=(
                narration_result.get("tokens_used", 0)
                if isinstance(narration_result, dict)
                else 0
            ),
            provider=(
                result.get("provider")
                or (
                    narration_result.get("provider")
                    if isinstance(narration_result, dict)
                    else None
                )
            ),
        )
        return success_response(
            data={
                "review_brief": review_brief,
                "history_signature": sign_officer_assistant_history(
                    officer_id=scope.officer_id,
                    application_id=scope.application_id,
                    content=narration,
                ),
                "conversation_id": data["conversation_id"],
                "response_time_ms": duration_ms,
                "request_id": request_id,
            },
            message="Officer AI response generated successfully",
        )


class OfficerStreamingChatView(AIRequestMetricsMixin, APIView):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ChatRateThrottle,)
    # Preflight failures are normal API responses. The actual generator is
    # returned as a StreamingHttpResponse with its own event-stream content type.
    renderer_classes = (JSONRenderer,)
    metrics_endpoint = "officer_chat_stream"

    def perform_content_negotiation(self, request, force=False):
        """Keep SSE negotiation local while rendering preflight errors as JSON."""
        accept = str(request.META.get("HTTP_ACCEPT", "") or "").lower()
        if "text/event-stream" in accept:
            return JSONRenderer(), "application/json"
        return super().perform_content_negotiation(request, force=force)

    def post(self, request):
        role_response = _require_officer(request)
        if role_response is not None:
            return role_response
        serializer = OfficerChatRequestSerializer(
            data=request.data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return error_response(
                message="Invalid officer assistant request",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        scope, response = resolve_officer_scope(request, data["application_id"])
        if response is not None:
            return response
        if not has_current_ai_consent(scope):
            return _consent_required_response()
        if not getattr(settings, "AI_ASSISTANT_ENABLED", True):
            return error_response(
                message="AI assistant is temporarily disabled",
                code="AI_ASSISTANT_DISABLED",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        request_id, validation_error = resolve_request_id(request)
        if validation_error:
            return validation_error
        request_claim = _claim_officer_request(scope, request_id, data)
        duplicate_response = _officer_idempotency_response(request_claim)
        if duplicate_response is not None:
            return duplicate_response
        try:
            record_officer_ai_access(scope, request_id, data["language"])
        except OfficerAIAuditUnavailable:
            _release_officer_request(scope, request_id)
            return error_response(
                message="AI access audit is temporarily unavailable",
                code="AI_AUDIT_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        scope_limited = _is_scope_limited_request(data)
        if data.get("intent") or scope_limited:
            llm = None
        else:
            llm, preflight_error = _officer_provider_preflight(
                scope, request_id, data["language"], time.monotonic(), stream=True
            )
            if preflight_error is not None:
                return preflight_error

        def event_stream():
            started = time.monotonic()
            increment(AI_ACTIVE_STREAMS)
            provider_stream = None
            terminal_emitted = False
            result_recorded = False
            lease_finalized = False
            response_parts = []
            response_chars = 0
            response_bytes = 0
            tool_names = []
            evidence = []
            max_stream_chars = max(
                1, int(settings.AI_ASSISTANT_STREAM_MAX_CHARS)
            )
            max_stream_bytes = max(
                1, int(settings.AI_ASSISTANT_STREAM_MAX_BYTES)
            )
            max_stream_duration = max(
                0.1,
                float(settings.AI_ASSISTANT_STREAM_MAX_DURATION_SECONDS),
            )

            def elapsed_ms():
                return max(0, int((time.monotonic() - started) * 1000))

            def record_result(outcome, *, duration_ms=None, diagnostic_code=None):
                nonlocal result_recorded
                if result_recorded:
                    return
                result_recorded = True
                record_officer_ai_result(
                    scope,
                    request_id,
                    data["language"],
                    outcome=outcome,
                    tool_names=tool_names,
                    duration_ms=elapsed_ms() if duration_ms is None else duration_ms,
                    diagnostic_code=diagnostic_code,
                )

            def complete_lease():
                nonlocal lease_finalized
                if not lease_finalized:
                    mark_complete(scope.customer_id, request_id)
                    lease_finalized = True

            def release_lease():
                nonlocal lease_finalized
                if not lease_finalized:
                    _release_officer_request(scope, request_id)
                    lease_finalized = True

            def stream_limit_event(limit):
                release_lease()
                code = (
                    "AI_PROVIDER_STREAM_DURATION_LIMIT"
                    if limit == "duration"
                    else "AI_PROVIDER_STREAM_OUTPUT_LIMIT"
                )
                record_result(code)
                _record_provider_metrics(
                    llm,
                    outcome="limit",
                    started=started,
                    operation="stream",
                )
                increment(
                    AI_STREAM_LIMIT_CANCELLATIONS,
                    provider=_safe_metric_provider(
                        getattr(llm, "provider", "unknown")
                    ),
                    limit=limit,
                )
                return self._event(
                    "error",
                    {
                        "content": "AI service is temporarily unavailable",
                        "code": code,
                        "request_id": request_id,
                    },
                )

            try:
                authorization_error = _authorization_error(scope)
                if authorization_error:
                    terminal_emitted = True
                    record_result(authorization_error)
                    _record_provider_metrics(
                        llm,
                        outcome=authorization_error,
                        started=started,
                        operation="stream",
                    )
                    yield self._event(
                        "error",
                        {
                            "content": "Officer access to this application is no longer available."
                            if authorization_error == "AI_OFFICER_SCOPE_CHANGED"
                            else "Customer AI consent is no longer available.",
                            "code": authorization_error,
                            "request_id": request_id,
                        },
                    )
                    return
                if data.get("intent"):
                    preset_result = _execute_preset_intent(
                        scope, request_id, data["intent"], evidence
                    )
                    tool_names.extend(preset_result["tools_called"])
                    # The renderer will produce a topic-specific unavailable
                    # brief from the failed evidence entry when needed.
                    provider_stream = iter([{"type": "done"}])
                elif scope_limited:
                    provider_stream = iter([{"type": "done"}])
                else:
                    provider_stream = llm.chat_with_tools_stream(
                        message=data["message"],
                        customer_id=scope.customer_id,
                        conversation_history=data["history"],
                        language=data["language"],
                        system_prompt=OFFICER_SYSTEM_PROMPT,
                        tools=OFFICER_TOOL_SCHEMAS,
                        tool_executor=_bound_executor(scope, request_id, evidence),
                        request_id=request_id,
                        officer_mode=True,
                    )
                for chunk in provider_stream:
                    if time.monotonic() - started >= max_stream_duration:
                        terminal_emitted = True
                        yield stream_limit_event("duration")
                        return
                    authorization_error = _authorization_error(scope)
                    if authorization_error:
                        terminal_emitted = True
                        record_result(authorization_error)
                        _record_provider_metrics(
                            llm,
                            outcome=authorization_error,
                            started=started,
                            operation="stream",
                        )
                        yield self._event(
                            "error",
                            {
                                "content": "Officer access to this application is no longer available."
                                if authorization_error == "AI_OFFICER_SCOPE_CHANGED"
                                else "Customer AI consent is no longer available.",
                                "code": authorization_error,
                                "request_id": request_id,
                            },
                        )
                        break
                    chunk_type = chunk.get("type")
                    name = str(chunk.get("name") or "")

                    if chunk_type == "tool_call":
                        if name in ALLOWED_TOOL_NAMES:
                            # Keep the SSE connection observable without exposing
                            # the private tool identifier or result contract.
                            yield ": processing\n\n"
                        continue
                    elif chunk_type == "tool_result":
                        if name in ALLOWED_TOOL_NAMES:
                            if name not in tool_names:
                                tool_names.append(name)
                    elif chunk_type == "token":
                        raw_content = str(chunk.get("content") or "")
                        next_chars = response_chars + len(raw_content)
                        next_bytes = response_bytes + len(
                            raw_content.encode("utf-8")
                        )
                        if next_chars > max_stream_chars:
                            terminal_emitted = True
                            yield stream_limit_event("characters")
                            return
                        if next_bytes > max_stream_bytes:
                            terminal_emitted = True
                            yield stream_limit_event("bytes")
                            return
                        response_chars = next_chars
                        response_bytes = next_bytes
                        response_parts.append(raw_content)
                    elif chunk_type == "done":
                        authorization_error = _authorization_error(scope)
                        if authorization_error:
                            terminal_emitted = True
                            record_result(authorization_error)
                            _record_provider_metrics(
                                llm,
                                outcome=authorization_error,
                                started=started,
                                operation="stream",
                            )
                            yield self._event(
                                "error",
                                {
                                    "content": "Officer access to this application is no longer available."
                                    if authorization_error == "AI_OFFICER_SCOPE_CHANGED"
                                    else "Customer AI consent is no longer available.",
                                    "code": authorization_error,
                                    "request_id": request_id,
                                },
                            )
                            break
                        if "model" in chunk and not isinstance(
                            chunk.get("model"), str
                        ):
                            raise ValueError("Malformed provider metadata")
                        if "tools_called" in chunk and not isinstance(
                            chunk.get("tools_called"), (list, tuple)
                        ):
                            raise ValueError("Malformed provider metadata")
                        tool_names[:] = _safe_tool_names(
                            [*tool_names, *(chunk.get("tools_called") or [])]
                        )
                        duration_ms = elapsed_ms()
                        review_brief, narration_result = _rendered_review_brief(
                            evidence, data
                        )
                        narration = sanitize_multiline_text(
                            escape_llm_output(review_brief["narration"])
                        )
                        review_brief["narration"] = narration
                        if (
                            len(narration) > max_stream_chars
                            or len(narration.encode("utf-8")) > max_stream_bytes
                        ):
                            terminal_emitted = True
                            yield stream_limit_event("characters")
                            return
                        try:
                            record_officer_review_brief(
                                scope,
                                request_id,
                                data["language"],
                                brief={
                                    key: value
                                    for key, value in review_brief.items()
                                    if key != "narration"
                                },
                            )
                        except OfficerAIAuditUnavailable:
                            release_lease()
                            record_result("AI_AUDIT_UNAVAILABLE")
                            terminal_emitted = True
                            yield self._event(
                                "error",
                                {
                                    "content": "AI review audit is temporarily unavailable",
                                    "code": "AI_AUDIT_UNAVAILABLE",
                                    "request_id": request_id,
                                },
                            )
                            return
                        terminal_event = self._event(
                            "done",
                            {
                                "response_time_ms": duration_ms,
                                "conversation_id": data["conversation_id"],
                                "review_brief": review_brief,
                                "history_signature": sign_officer_assistant_history(
                                    officer_id=scope.officer_id,
                                    application_id=scope.application_id,
                                    content=narration,
                                ),
                                "request_id": request_id,
                            },
                        )
                        record_result(
                            "success",
                            duration_ms=duration_ms,
                            diagnostic_code=(
                                narration_result.get("diagnostic_code")
                                if isinstance(narration_result, dict)
                                else None
                            ),
                        )
                        complete_lease()
                        _record_provider_metrics(
                            llm,
                            outcome="success",
                            started=started,
                            operation="stream",
                            tokens_used=(
                                narration_result.get("tokens_used", 0)
                                if isinstance(narration_result, dict)
                                else 0
                            ),
                            provider=(
                                chunk.get("provider")
                                or getattr(llm, "provider", None)
                                or (
                                    narration_result.get("provider")
                                    if isinstance(narration_result, dict)
                                    else None
                                )
                            ),
                        )
                        terminal_emitted = True
                        yield terminal_event
                        break
                    elif chunk_type == "error":
                        outcome = _safe_controlled_error_code(chunk.get("code"))
                        terminal_emitted = True
                        record_result(outcome)
                        _record_provider_metrics(
                            llm,
                            outcome="error",
                            started=started,
                            operation="stream",
                            provider=chunk.get("provider"),
                        )
                        yield self._event(
                            "error",
                            {
                                "content": "AI service is temporarily unavailable",
                                "code": outcome,
                                "request_id": request_id,
                            },
                        )
                        break

                if not terminal_emitted:
                    authorization_error = _authorization_error(scope)
                    if authorization_error:
                        terminal_emitted = True
                        record_result(authorization_error)
                        _record_provider_metrics(
                            llm,
                            outcome=authorization_error,
                            started=started,
                            operation="stream",
                        )
                        yield self._event(
                            "error",
                            {
                                "content": "Officer access to this application is no longer available."
                                if authorization_error == "AI_OFFICER_SCOPE_CHANGED"
                                else "Customer AI consent is no longer available.",
                                "code": authorization_error,
                                "request_id": request_id,
                            },
                        )
                        return
                    terminal_emitted = True
                    record_result("AI_STREAM_INCOMPLETE")
                    _record_provider_metrics(
                        llm,
                        outcome="incomplete",
                        started=started,
                        operation="stream",
                    )
                    yield self._event(
                        "error",
                        {
                            "content": "AI stream ended unexpectedly",
                            "code": "AI_STREAM_INCOMPLETE",
                            "request_id": request_id,
                        },
                    )
            except GeneratorExit:
                if not terminal_emitted:
                    record_result("disconnected")
                    _record_provider_metrics(
                        llm,
                        outcome="disconnect",
                        started=started,
                        operation="stream",
                    )
                raise
            except Exception:
                if not terminal_emitted:
                    terminal_emitted = True
                    record_result("AI_STREAM_ERROR")
                    _record_provider_metrics(
                        llm,
                        outcome="error",
                        started=started,
                        operation="stream",
                    )
                    logger.error(
                        "Officer AI stream failed",
                        extra={"request_id": request_id},
                    )
                    yield self._event(
                        "error",
                        {
                            "content": "Stream error occurred",
                            "code": "AI_STREAM_ERROR",
                            "request_id": request_id,
                        },
                    )
            finally:
                release_lease()
                close_stream = getattr(provider_stream, "close", None)
                if callable(close_stream):
                    try:
                        close_stream()
                    except Exception:
                        logger.warning(
                            "Officer AI provider stream cleanup failed",
                            extra={"request_id": request_id},
                        )
                decrement(AI_ACTIVE_STREAMS)

        return self._streaming_response(event_stream())

    @staticmethod
    def _event(name, payload):
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    @staticmethod
    def _streaming_response(stream):
        response = StreamingHttpResponse(stream, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
