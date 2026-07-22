"""Canonical notification-owner identity and query helpers."""

SUPPORTED_NOTIFICATION_USER_TYPES = {"customer", "loan_officer", "admin"}


def normalize_notification_user_type(user_type):
    """Normalize authentication roles to values stored on notifications."""
    normalized = str(user_type or "").strip().lower().replace("-", "_")
    aliases = {
        "superadmin": "admin",
        "super_admin": "admin",
        "officer": "loan_officer",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SUPPORTED_NOTIFICATION_USER_TYPES else ""


def notification_owner_identity(user):
    """Return the role-qualified notification identity for an auth user."""
    user_id = str(
        getattr(user, "customer_id", "") or getattr(user, "user_id", "") or ""
    ).strip()
    user_type = normalize_notification_user_type(getattr(user, "role", ""))
    return user_id, user_type


def build_notification_owner_query_from_values(user_id, user_type):
    """Build a strict owner query requiring both ID and normalized role."""
    normalized_id = str(user_id or "").strip()
    normalized_type = normalize_notification_user_type(user_type)
    if not normalized_id or not normalized_type:
        return {"_id": None}
    return {"user_id": normalized_id, "user_type": normalized_type}


def build_notification_owner_query(user):
    user_id, user_type = notification_owner_identity(user)
    return build_notification_owner_query_from_values(user_id, user_type)


def notification_group_name(user_id, user_type):
    """Return a role-qualified Channels group for one notification owner."""
    owner_query = build_notification_owner_query_from_values(user_id, user_type)
    if owner_query == {"_id": None}:
        return None
    return f"notifications_{owner_query['user_type']}_{owner_query['user_id']}"
