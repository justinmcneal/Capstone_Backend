"""Shared serialization helpers for the loans domain."""


def serialize_internal_note(note):
    """Normalize a stored note entry for API responses."""
    if not note:
        return None

    created_at = note.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()

    return {
        "content": note.get("content", ""),
        "author_id": note.get("author_id"),
        "author_role": note.get("author_role"),
        "created_at": created_at,
    }
