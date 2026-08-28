import re
import unicodedata
import uuid

from rest_framework import serializers

from ai_assistant.services.request_limits import validate_chat_message


_OFFICER_CONTEXT_RESTRICTED_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:customer|borrower|applicant)\s+(?:name|email|phone|mobile|address)\s*[:=-]",
        r"\b(?:customer|borrower|applicant)\s*:\s*[a-z][a-z' -]{2,}",
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
        r"(?<!\w)\+\d{1,3}(?:[\s().-]*\d){7,14}(?!\w)",
        r"(?<!\w)(?:00\d{1,3}|011)[\s().-]*(?:\d[\s().-]*){7,14}(?!\w)",
        r"(?<!\w)(?:\d[\s().-]*){10,15}(?!\w)",
        r"(?<!\w)(?:\+?63|0)9\d{9}(?!\w)",
        r"\b(?:phone|mobile|address|government\s+id|national\s+id|passport|id\s+number|date\s+of\s+birth|dob)\b",
        r"\b(?:document|file)\s+(?:filename|name|content|path|url|storage)\b",
        r"\b[\w.-]+\.(?:pdf|png|jpe?g|docx?|csv)\b",
        r"[\\/][^\s]+",
        r"\b(?:wallet|transaction\s+hash|payment\s+reference|reference\s+number)\b",
        r"\b(?:internal\s+note|staff\s+(?:password|credential)|password|secret|api\s+key|token|credential)\b",
        r"\b0x[0-9a-f]{8,}\b",
        r"\b(?:pay|txn|ref)[-_][A-Za-z0-9]{4,}\b",
        r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{8})\b",
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*|\s+)\d{4}\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b",
        r"\b\d{1,5}\s+[A-Za-z][A-Za-z.'-]*(?:,\s*|\s+)[A-Za-z][A-Za-z.'-]*\s+(?:city|municipality|barangay)\b",
        r"\b\d{1,6}\s+[A-Za-z][A-Za-z.'-]{2,}(?:\s+[A-Za-z][A-Za-z.'-]{2,}){1,4}(?:,|$)",
    )
)
_OFFICER_CONTEXT_NAME_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:customer|borrower|applicant)\s+(?:mr|mrs|ms|miss)?\.?\s*[a-z][a-z'-]{1,30}\s+[a-z][a-z'-]{1,30}(?:['’]s)?\b",
    )
)
_OFFICER_CONTEXT_NAME_PATTERN = re.compile(
    r"\b([a-z][a-z'-]{1,30})\s+([a-z][a-z'-]{1,30})(?:['’]s)?\b",
    re.IGNORECASE,
)
_OFFICER_CONTEXT_NAME_STOP_WORDS = frozenset(
    {
        "about",
        "application",
        "and",
        "are",
        "call",
        "contact",
        "current",
        "document",
        "documents",
        "for",
        "earlier",
        "explain",
        "is",
        "loan",
        "missing",
        "next",
        "payment",
        "please",
        "profile",
        "readiness",
        "repayment",
        "review",
        "show",
        "status",
        "summary",
        "summarize",
        "question",
        "tell",
        "the",
        "what",
        "with",
    }
)
_OFFICER_CONTEXT_SAFE_PHRASES = frozenset(
    {
        "application summary",
        "document review",
        "loan application",
        "missing documents",
        "payment status",
        "profile readiness",
        "repayment status",
        "review readiness",
        "working capital",
    }
)
_OFFICER_CONTEXT_ERROR = "This request cannot be processed"


def _validate_officer_context(value):
    normalized = re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).casefold(),
    ).strip()
    words = re.findall(r"[a-z][a-z'-]{1,30}", normalized)
    likely_name = any(
        first not in _OFFICER_CONTEXT_NAME_STOP_WORDS
        and second not in _OFFICER_CONTEXT_NAME_STOP_WORDS
        and f"{first} {second}" not in _OFFICER_CONTEXT_SAFE_PHRASES
        for first, second in zip(words, words[1:])
    )
    if any(pattern.search(normalized) for pattern in _OFFICER_CONTEXT_RESTRICTED_PATTERNS) or any(
        pattern.search(normalized) for pattern in _OFFICER_CONTEXT_NAME_PATTERNS
    ) or likely_name:
        raise serializers.ValidationError(_OFFICER_CONTEXT_ERROR)


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
        _validate_officer_context(message)
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
            _validate_officer_context(cleaned_content)
            normalized.append({"role": role, "content": cleaned_content})

        return normalized[-6:]

    def validate(self, attrs):
        attrs.setdefault("conversation_id", str(uuid.uuid4()))
        return attrs
