"""Loan-officer-only AI assistant HTTP boundaries."""

import json
import logging
import re
import time
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.throttles import ChatRateThrottle
from accounts.utils.validation_utils import escape_llm_output, sanitize_multiline_text
from ai_assistant.serializers.officer import OfficerChatRequestSerializer
from ai_assistant.services import get_llm_service
from ai_assistant.services.officer_audit import (
    OfficerAIAuditUnavailable,
    record_officer_ai_access,
    record_officer_ai_result,
)
from ai_assistant.services.officer_prompt import (
    OFFICER_SYSTEM_PROMPT,
    officer_suggestions,
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
from ai_assistant.metrics import (
    AI_ACTIVE_STREAMS,
    AI_PROVIDER_LATENCY,
    AI_PROVIDER_REQUESTS,
    AI_TOKENS,
    decrement,
    increment,
    observe,
)
from ai_assistant.views.chat_views import AIRequestMetricsMixin

logger = logging.getLogger("ai_assistant")

ALLOWED_TOOL_NAMES = frozenset(
    schema["function"]["name"] for schema in OFFICER_TOOL_SCHEMAS
)
SAFE_CONTROLLED_ERROR_CODES = frozenset(
    {
        "AI_PROVIDER_BUSY",
        "AI_PROVIDER_CIRCUIT_OPEN",
        "AI_PROVIDER_ERROR",
        "AI_PROVIDER_STREAM_MALFORMED",
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


def _consent_required_response():
    return error_response(
        message="Current customer AI consent is required to use this feature",
        code="CONSENT_REQUIRED",
        status_code=status.HTTP_403_FORBIDDEN,
    )


def _require_officer(request):
    allowed, actor_or_response = AccessControlMixin().require_roles(
        request, {"loan_officer"}
    )
    return None if allowed else actor_or_response


def _safe_tool_names(values):
    names = []
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


def _bound_executor(scope, request_id):
    captured_request_id = request_id

    def execute(tool_name, tool_args, _customer_id, request_id=None):
        return execute_officer_tool_result(
            tool_name,
            tool_args,
            scope,
            request_id=request_id or captured_request_id,
        )

    return execute


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
        try:
            record_officer_ai_access(scope, request_id, data["language"])
        except OfficerAIAuditUnavailable:
            return error_response(
                message="AI access audit is temporarily unavailable",
                code="AI_AUDIT_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        started = time.monotonic()
        try:
            llm = get_llm_service(use_case="chat")
            provider_available = llm.is_available()
        except Exception:
            _record_provider_metrics(
                None,
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
                "Officer AI provider setup failed",
                extra={"request_id": request_id},
            )
            return error_response(
                message="Failed to process officer AI request",
                code="AI_PROVIDER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if not provider_available:
            _record_provider_metrics(
                llm,
                outcome="unavailable",
                started=started,
                operation="chat",
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome="AI_PROVIDER_UNAVAILABLE",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return error_response(
                message="AI service is currently unavailable",
                code="AI_PROVIDER_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            result = llm.chat_with_tools(
                message=data["message"],
                customer_id=scope.customer_id,
                conversation_history=data["history"],
                language=data["language"],
                system_prompt=OFFICER_SYSTEM_PROMPT,
                tools=OFFICER_TOOL_SCHEMAS,
                tool_executor=_bound_executor(scope, request_id),
                request_id=request_id,
            )
        except Exception:
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
        duration_ms = _safe_duration_ms(
            result.get("response_time_ms"),
            (time.monotonic() - started) * 1000,
        )
        tool_names = _safe_tool_names(result.get("tools_called"))
        if not result.get("success"):
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

        ai_response = sanitize_multiline_text(
            escape_llm_output(result.get("response", ""))
        )
        if not ai_response:
            _record_provider_metrics(
                llm,
                outcome="empty",
                started=started,
                operation="chat",
                provider=result.get("provider"),
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome="AI_EMPTY_RESPONSE",
                tool_names=tool_names,
                duration_ms=duration_ms,
            )
            return error_response(
                message="AI returned an empty response",
                code="AI_EMPTY_RESPONSE",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        authorization_error = _authorization_error(scope)
        if authorization_error:
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
        )
        _record_provider_metrics(
            llm,
            outcome="success",
            started=started,
            operation="chat",
            tokens_used=result.get("tokens_used"),
            provider=result.get("provider"),
        )
        return success_response(
            data={
                "response": ai_response,
                "conversation_id": data["conversation_id"],
                "model": _safe_model_identifier(llm),
                "response_time_ms": duration_ms,
                "request_id": request_id,
                "tools_called": tool_names,
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
        try:
            record_officer_ai_access(scope, request_id, data["language"])
        except OfficerAIAuditUnavailable:
            return error_response(
                message="AI access audit is temporarily unavailable",
                code="AI_AUDIT_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            llm = get_llm_service(use_case="chat")
            provider_available = llm.is_available()
        except Exception:
            _record_provider_metrics(
                None,
                outcome="error",
                started=time.monotonic(),
                operation="stream",
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome="AI_PROVIDER_ERROR",
                duration_ms=0,
            )
            logger.error(
                "Officer AI stream provider setup failed",
                extra={"request_id": request_id},
            )
            return error_response(
                message="Failed to process officer AI stream request",
                code="AI_PROVIDER_ERROR",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if not provider_available:
            _record_provider_metrics(
                llm,
                outcome="unavailable",
                started=time.monotonic(),
                operation="stream",
            )
            record_officer_ai_result(
                scope,
                request_id,
                data["language"],
                outcome="AI_PROVIDER_UNAVAILABLE",
                duration_ms=0,
            )
            return error_response(
                message="AI service is currently unavailable",
                code="AI_PROVIDER_UNAVAILABLE",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        def event_stream():
            started = time.monotonic()
            increment(AI_ACTIVE_STREAMS)
            provider_stream = None
            terminal_emitted = False
            result_recorded = False
            response_parts = []
            tool_names = []

            def elapsed_ms():
                return max(0, int((time.monotonic() - started) * 1000))

            def record_result(outcome, *, duration_ms=None):
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
                )

            try:
                provider_stream = llm.chat_with_tools_stream(
                    message=data["message"],
                    customer_id=scope.customer_id,
                    conversation_history=data["history"],
                    language=data["language"],
                    system_prompt=OFFICER_SYSTEM_PROMPT,
                    tools=OFFICER_TOOL_SCHEMAS,
                    tool_executor=_bound_executor(scope, request_id),
                    request_id=request_id,
                )
                for chunk in provider_stream:
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
                            yield self._event("tool_call", {"name": name})
                    elif chunk_type == "tool_result":
                        if name in ALLOWED_TOOL_NAMES:
                            if name not in tool_names:
                                tool_names.append(name)
                            yield self._event(
                                "tool_result",
                                {"name": name, "success": bool(chunk.get("success"))},
                            )
                    elif chunk_type == "token":
                        raw_content = str(chunk.get("content") or "")
                        response_parts.append(raw_content)
                        yield self._event(
                            "token", {"content": escape_llm_output(raw_content)}
                        )
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
                        tool_names[:] = _safe_tool_names(
                            [*tool_names, *(chunk.get("tools_called") or [])]
                        )
                        duration_ms = elapsed_ms()
                        safe_response = sanitize_multiline_text(
                            escape_llm_output("".join(response_parts))
                        )
                        if not safe_response:
                            terminal_event = self._event(
                                "error",
                                {
                                    "content": "AI returned an empty response",
                                    "code": "AI_EMPTY_RESPONSE",
                                    "request_id": request_id,
                                },
                            )
                            record_result(
                                "AI_EMPTY_RESPONSE", duration_ms=duration_ms
                            )
                            _record_provider_metrics(
                                llm,
                                outcome="empty",
                                started=started,
                                operation="stream",
                                provider=chunk.get("provider"),
                            )
                            terminal_emitted = True
                            yield terminal_event
                        else:
                            terminal_event = self._event(
                                "done",
                                {
                                    "model": _safe_model_identifier(llm),
                                    "tokens_used": _safe_token_count(
                                        chunk.get("tokens_used")
                                    ),
                                    "response_time_ms": duration_ms,
                                    "conversation_id": data["conversation_id"],
                                    "tools_called": tool_names,
                                    "request_id": request_id,
                                },
                            )
                            record_result("success", duration_ms=duration_ms)
                            _record_provider_metrics(
                                llm,
                                outcome="success",
                                started=started,
                                operation="stream",
                                tokens_used=_safe_token_count(
                                    chunk.get("tokens_used")
                                ),
                                provider=chunk.get("provider"),
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
