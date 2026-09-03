import re
import unicodedata
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
        r"\b\d{1,6}\s+[\w][\w.'’-]{1,}(?:\s+[\w][\w.'’-]{1,}){0,4}(?:,|$)",
    )
)
_OFFICER_CONTEXT_SAFE_PROMPTS = frozenset(
    {
        "summarize this application's review readiness",
        "summarize review readiness",
        "review summary",
        "review this application",
        "review missing documents and repayment status",
        "what documents are present",
        "what profile information is still incomplete",
        "summarize the required document review statuses",
        "explain the current repayment summary",
        "ibuod ang kahandaan ng aplikasyon para sa pagsusuri",
        "ano pa ang kulang sa profile bago ang pagsusuri",
        "ibuod ang katayuan ng mga kinakailangang dokumento",
        "ipaliwanag ang kasalukuyang buod ng pagbabayad",
        "summarize what is still needed before review",
        "review missing documents",
        "can you tell me what needs attention in this record",
    }
)
_OFFICER_CONTEXT_NAME_AFTER_CONTEXT = re.compile(
    r"\b(?:review|about|for|contact|call|customer|borrower|applicant)\s+"
    r"(?:mr|mrs|ms|miss)?\.?\s*[\w'’-]+(?:\s+[\w'’-]+)?\b",
    re.IGNORECASE,
)
_OFFICER_CONTEXT_UNICODE_NAME = re.compile(
    r"(?<!\w)[\u0400-\u04ff\u0370-\u03ff]+\s+[\u0400-\u04ff\u0370-\u03ff]+(?!\w)"
)
_OFFICER_CONTEXT_LATIN_NAME = re.compile(
    r"(?<!\w)[A-Z][a-zÀ-ÖØ-öø-ÿ'’-]{1,30}\s+[A-Z][a-zÀ-ÖØ-öø-ÿ'’-]{1,30}(?!\w)"
)
_OFFICER_CONTEXT_BARE_NAME = re.compile(
    r"(?<!\w)([^\W\d_][\w'’-]{1,30})\s+"
    r"([^\W\d_][\w'’-]{1,30})(?!\w)",
    re.IGNORECASE,
)
_OFFICER_CONTEXT_SAFE_WORD_PAIRS = frozenset(
    {
        "application summary",
        "document review",
        "explain current",
        "earlier question",
        "loan application",
        "missing documents",
        "payment status",
        "profile readiness",
        "repayment status",
        "review readiness",
        "review summary",
        "what status",
    }
)
_OFFICER_CONTEXT_STOP_WORDS = frozenset(
    {
        "about", "and", "application", "are", "call", "contact", "current",
        "document", "documents", "earlier", "explain", "for", "incomplete",
        "information", "is", "loan", "missing", "next", "payment", "please",
        "profile", "question", "readiness", "repayment", "required", "review",
        "show", "still", "status", "statuses", "summary", "summarize", "tell",
        "explain", "stream",
        "the", "this", "what", "with",
        # Common Tagalog function/context words must not look like a bare name
        # when officers ask a normal bilingual application question.
        "ano", "ang", "aplikasyon", "ito", "kulang", "na", "sa",
    }
)
_OFFICER_CONTEXT_ERROR = "This request cannot be processed"
OFFICER_PRIVACY_BLOCKED_CODE = "AI_OFFICER_PRIVACY_BLOCKED"
OFFICER_REQUEST_INVALID_CODE = "AI_OFFICER_REQUEST_INVALID"
_OFFICER_CONTEXT_UNICODE_SLASHES = frozenset({"⁄", "∕", "／", "⧸"})


def _canonicalize_officer_detection_text(value):
    """Normalize Unicode separators before running the privacy detectors."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    canonical = []
    for character in normalized:
        if unicodedata.category(character) == "Cf":
            continue
        if character in _OFFICER_CONTEXT_UNICODE_SLASHES:
            canonical.append("/")
            continue
        category = unicodedata.category(character)
        if category == "Pd":
            canonical.append("-")
        elif character in {"．", "。", "｡"}:
            canonical.append(".")
        elif category.startswith("P") and character not in {"'", "’", ".", "+", "@", "-", "/"}:
            canonical.append(" ")
        else:
            canonical.append(character)
    return re.sub(r"\s+", " ", "".join(canonical)).strip()


def _validate_officer_context(value):
    normalized = re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).casefold(),
    ).strip()
    safe_prompt_key = normalized.strip(" .!?;:")
    if safe_prompt_key in _OFFICER_CONTEXT_SAFE_PROMPTS:
        return
    detection_text = _canonicalize_officer_detection_text(value)
    if any(
        unicodedata.category(character).startswith("L")
        and "LATIN" not in unicodedata.name(character, "")
        for character in normalized
    ):
        raise serializers.ValidationError(
            _OFFICER_CONTEXT_ERROR,
            code=OFFICER_PRIVACY_BLOCKED_CODE,
        )
    bare_name = any(
        f"{first} {second}" not in _OFFICER_CONTEXT_SAFE_WORD_PAIRS
        and first not in _OFFICER_CONTEXT_STOP_WORDS
        and second not in _OFFICER_CONTEXT_STOP_WORDS
        for first, second in _OFFICER_CONTEXT_BARE_NAME.findall(detection_text)
    )
    single_name = bool(
        re.fullmatch(r"[^\W\d_][^\W\d_']{1,30}", detection_text)
        and detection_text not in _OFFICER_CONTEXT_STOP_WORDS
    )
    separated_name = any(
        first not in _OFFICER_CONTEXT_STOP_WORDS
        and second not in _OFFICER_CONTEXT_STOP_WORDS
        for first, second in re.findall(
            r"(?<!\w)([^\W\d_]{2,30})[.\-]([^\W\d_]{2,30})(?!\w)",
            detection_text,
        )
    )
    context_match = _OFFICER_CONTEXT_NAME_AFTER_CONTEXT.search(detection_text)
    context_tokens = context_match.group(0).split()[1:] if context_match else ()
    context_name_after_context = any(
        token not in _OFFICER_CONTEXT_STOP_WORDS
        and token not in {"mr", "mrs", "ms", "miss"}
        for token in context_tokens
    )
    if (
        any(pattern.search(detection_text) for pattern in _OFFICER_CONTEXT_RESTRICTED_PATTERNS)
        or context_name_after_context
        or _OFFICER_CONTEXT_UNICODE_NAME.search(detection_text)
        or _OFFICER_CONTEXT_LATIN_NAME.search(str(value or ""))
        or bare_name
        or single_name
        or separated_name
        or re.search(r"(?<!\w)(?:\d[\s().,/+-]*){7,}(?!\w)", detection_text)
    ):
        raise serializers.ValidationError(
            _OFFICER_CONTEXT_ERROR,
            code=OFFICER_PRIVACY_BLOCKED_CODE,
        )


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
            # Greetings and clearly unsupported requests are handled locally by
            # the officer policy boundary. Keep them out of the conservative
            # name heuristic so local guidance can be rendered safely.
            policy_category = officer_policy_category(message)
            privacy_violations = officer_text_privacy_violations(message)
            local_only = policy_category in {"help", "unsupported"} and not privacy_violations
            if policy_category == "code" and set(privacy_violations) <= {"name"}:
                local_only = True
            if not local_only:
                _validate_officer_context(message)
        attrs.setdefault("conversation_id", str(uuid.uuid4()))
        return attrs
