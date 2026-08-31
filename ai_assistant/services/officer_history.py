"""Sign ephemeral officer-assistant history without storing conversation text."""

import hashlib

from django.core import signing


OFFICER_HISTORY_SALT = "ai_assistant.officer_history.v1"
OFFICER_HISTORY_MAX_AGE_SECONDS = 60 * 60


def _content_sha256(content):
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()


def sign_officer_assistant_history(*, officer_id, application_id, content):
    return signing.dumps(
        {
            "officer_id": str(officer_id),
            "application_id": str(application_id),
            "content_sha256": _content_sha256(content),
        },
        salt=OFFICER_HISTORY_SALT,
        compress=True,
    )


def verify_officer_assistant_history(
    signature, *, officer_id, application_id, content
):
    if not isinstance(signature, str) or not signature or len(signature) > 2048:
        return False
    try:
        payload = signing.loads(
            signature,
            salt=OFFICER_HISTORY_SALT,
            max_age=OFFICER_HISTORY_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return False
    return payload == {
        "officer_id": str(officer_id),
        "application_id": str(application_id),
        "content_sha256": _content_sha256(content),
    }
