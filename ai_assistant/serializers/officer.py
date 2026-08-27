import uuid

from rest_framework import serializers

from ai_assistant.services.request_limits import validate_chat_message


class OfficerChatRequestSerializer(serializers.Serializer):
    """Validate the bounded request envelope for the officer assistant."""

    message = serializers.CharField(required=True, allow_blank=False)
    application_id = serializers.CharField(required=True, allow_blank=False)
    conversation_id = serializers.CharField(required=False, allow_blank=False)
    language = serializers.CharField(required=False, default="en", allow_blank=False)
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

    def validate_history(self, value):
        normalized = []
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
            normalized.append({"role": role, "content": cleaned_content})

        return normalized[-6:]

    def validate(self, attrs):
        attrs.setdefault("conversation_id", str(uuid.uuid4()))
        return attrs
