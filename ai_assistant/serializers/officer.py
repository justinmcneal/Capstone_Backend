import uuid

from rest_framework import serializers

from ai_assistant.services.officer_history import verify_officer_assistant_history
from ai_assistant.services.officer_policy import (
    officer_policy_category,
)
from ai_assistant.services.officer_privacy import officer_text_privacy_violations
from ai_assistant.services.officer_prompt import (
    canonical_officer_question,
    is_approved_officer_action_message,
    officer_action_intent_for_message,
)
from ai_assistant.services.request_limits import (
    AI_ASSISTANT_HISTORY_MAX_MESSAGES,
    validate_chat_message,
)

_OFFICER_CONTEXT_ERROR = "This request cannot be processed"
OFFICER_PRIVACY_BLOCKED_CODE = "AI_OFFICER_PRIVACY_BLOCKED"
OFFICER_REQUEST_INVALID_CODE = "AI_OFFICER_REQUEST_INVALID"


def _validate_officer_context(value):
    violations = officer_text_privacy_violations(value)
    if violations:
        raise serializers.ValidationError(
            _OFFICER_CONTEXT_ERROR,
            code=OFFICER_PRIVACY_BLOCKED_CODE,
        )
    return

class OfficerChatRequestSerializer(serializers.Serializer):
    """Validate the bounded request envelope for the officer assistant."""

    message = serializers.CharField(required=False, allow_blank=False)
    application_id = serializers.CharField(required=True, allow_blank=False)
    conversation_id = serializers.CharField(required=False, allow_blank=False)
    language = serializers.CharField(required=False, default="en", allow_blank=False)
    intent = serializers.CharField(required=False, allow_blank=False)
    history = serializers.ListField(required=False, default=list, allow_empty=True)

    @staticmethod
    def _message_error(response):
        payload = getattr(response, "data", {}) or {}
        errors = payload.get("errors")
        if isinstance(errors, dict) and errors:
            return next(iter(errors.values()))
        return payload.get("message", "Invalid message")

    def validate_message(self, value):
        message, error = validate_chat_message(
            value,
            self.context.get("request"),
        )
        if error:
            raise serializers.ValidationError(self._message_error(error))
        return message

    def validate_conversation_id(self, value):
        try:
            return str(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise serializers.ValidationError("Invalid UUID format") from exc

    def validate_language(self, value):
        language = str(value).strip().lower()
        if language not in {"en", "tl"}:
            raise serializers.ValidationError("Use one of: en, tl")
        return language

    def validate_intent(self, value):
        from ai_assistant.services.officer_prompt import OFFICER_SUGGESTION_INTENTS

        intent = str(value).strip()
        if intent not in OFFICER_SUGGESTION_INTENTS:
            raise serializers.ValidationError("Use one of the supported suggestion intents")
        return intent

    def validate_history(self, value):
        normalized = []
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        officer_id = getattr(actor, "customer_id", None) or getattr(
            actor, "id", None
        )
        application_id = self.initial_data.get("application_id")
        history_language = self.initial_data.get("language", "en")
        for index, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise serializers.ValidationError(
                    {str(index): "Each history entry must be an object"}
                )

            role = entry.get("role")
            if role not in {"user", "assistant"}:
                raise serializers.ValidationError(
                    {str(index): {"role": "Use one of: user, assistant"}}
                )

            content = entry.get("content")
            if not isinstance(content, str):
                raise serializers.ValidationError(
                    {str(index): {"content": "This field must be a string"}}
                )

            cleaned_content, error = validate_chat_message(content)
            if error:
                raise serializers.ValidationError(
                    {str(index): {"content": self._message_error(error)}}
                )
            if role == "assistant":
                if not verify_officer_assistant_history(
                    entry.get("history_signature"),
                    officer_id=officer_id,
                    application_id=application_id,
                    content=content,
                ):
                    raise serializers.ValidationError(
                        {str(index): {"content": _OFFICER_CONTEXT_ERROR}}
                    )
            else:
                history_intent = officer_action_intent_for_message(
                    cleaned_content, history_language
                )
                if history_intent:
                    cleaned_content = canonical_officer_question(
                        history_intent, history_language
                    )
                else:
                    _validate_officer_context(cleaned_content)
            normalized.append({"role": role, "content": cleaned_content})

        return normalized[-AI_ASSISTANT_HISTORY_MAX_MESSAGES:]

    def validate(self, attrs):
        message = attrs.get("message")
        intent = attrs.get("intent")
        language = attrs.get("language", "en")

        if intent:
            if message:
                privacy_violations = officer_text_privacy_violations(message)
                if privacy_violations and not (
                    set(privacy_violations) == {"name"}
                    and is_approved_officer_action_message(message, intent, language)
                ):
                    raise serializers.ValidationError(
                        {
                            "message": serializers.ErrorDetail(
                                _OFFICER_CONTEXT_ERROR,
                                code=OFFICER_PRIVACY_BLOCKED_CODE,
                            )
                        }
                    )
                if not is_approved_officer_action_message(message, intent, language):
                    raise serializers.ValidationError(
                        {"message": "The message does not match the selected suggestion"}
                    )
            attrs["message"] = canonical_officer_question(intent, language)
        elif not message:
            raise serializers.ValidationError(
                {"message": "This field is required unless an intent is supplied"}
            )
        else:
            typed_action_intent = officer_action_intent_for_message(message, language)
            if typed_action_intent:
                # Exact server-owned action labels are safe to normalize before
                # the conservative name detector. This keeps manually typed
                # labels equivalent to their one-click counterparts without
                # allowing arbitrary free text to bypass privacy validation.
                attrs["message"] = canonical_officer_question(
                    typed_action_intent, language
                )
            else:
                # Greetings and clearly unsupported requests are handled locally by
                # the officer policy boundary. Keep them out of the conservative
                # name heuristic so local guidance can be rendered safely.
                policy_category = officer_policy_category(message)
                privacy_violations = officer_text_privacy_violations(message)
                local_only = policy_category in {
                    "help",
                    "unsupported",
                    "read_only",
                    "ambiguous",
                } and not privacy_violations
                if policy_category == "code" and set(privacy_violations) <= {"name"}:
                    local_only = True
                if not local_only:
                    _validate_officer_context(message)
        attrs.setdefault("conversation_id", str(uuid.uuid4()))
        return attrs
