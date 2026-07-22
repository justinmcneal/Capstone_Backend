"""Reusable in-app notifications for assignment lifecycle events."""

import logging
from datetime import datetime, timezone

from notifications.models.notification import Notification
from notifications.services.websocket_service import (
    broadcast_notification_to_user,
    serialize_notification_for_ws,
)

logger = logging.getLogger("notifications.assignment")


def _party_metadata(party):
    if not party:
        return None
    return {
        "id": str(party.get("id")) if party.get("id") is not None else None,
        "user_type": party.get("user_type"),
        "name": party.get("name"),
    }


def _create_notification(
    *,
    recipient,
    notification_type,
    subject,
    message,
    metadata,
    related_type,
    related_id,
    occurred_at,
):
    """Persist one assignment notification and broadcast it best-effort."""
    notification = Notification(
        user_id=str(recipient["id"]),
        user_type=recipient["user_type"],
        recipient_email=recipient.get("email", ""),
        recipient_name=recipient["name"],
        notification_type=notification_type,
        subject=subject,
        message=message,
        related_type=related_type,
        related_id=str(related_id),
        metadata=metadata,
        channel="in_app",
        status="sent",
        created_at=occurred_at,
    )
    notification.save()

    try:
        broadcast_notification_to_user(
            recipient["id"],
            recipient["user_type"],
            serialize_notification_for_ws(notification),
        )
    except Exception:
        logger.exception(
            "Failed to broadcast assignment notification %s", notification.id
        )

    return notification


def publish_assignment_notifications(
    *,
    entity_name,
    assigned_by,
    assigned_to=None,
    previous_assignee=None,
    related_type,
    related_id,
    entity_type="loan_application",
    occurred_at=None,
):
    """
    Persist and broadcast notifications for assign, reassign, or unassign.

    Party dictionaries use: id, user_type, name, and optional email. The
    function deliberately does not send email or push notifications because
    these staff events are scoped to the existing web notification center.
    """
    if not assigned_to and not previous_assignee:
        raise ValueError("An assignment event requires an assignee")

    occurred_at = occurred_at or datetime.now(timezone.utc)
    actor_name = assigned_by["name"] if assigned_by else "System"

    if assigned_to and previous_assignee:
        event_type = "application_reassigned"
    elif assigned_to:
        event_type = "application_assigned"
    else:
        event_type = "application_unassigned"

    base_metadata = {
        "event_type": event_type,
        "assigned_by": _party_metadata(assigned_by),
        "assigned_to": _party_metadata(assigned_to),
        "previous_assignee": _party_metadata(previous_assignee),
        "entity": {
            "id": str(related_id),
            "type": entity_type,
            "name": entity_name,
        },
        "occurred_at": occurred_at.isoformat(),
    }

    notification_specs = []

    if assigned_by:
        if event_type == "application_assigned":
            message = f"You assigned {entity_name} to {assigned_to['name']}."
            subject = "Application assignment confirmed"
        elif event_type == "application_reassigned":
            message = (
                f"You reassigned {entity_name} from "
                f"{previous_assignee['name']} to {assigned_to['name']}."
            )
            subject = "Application reassignment confirmed"
        else:
            message = f"You unassigned {entity_name} from {previous_assignee['name']}."
            subject = "Application unassignment confirmed"

        notification_specs.append(
            (assigned_by, event_type, subject, message, "assigner")
        )

    if assigned_to:
        assignment_source = f"by {actor_name}" if assigned_by else "automatically"
        notification_specs.append(
            (
                assigned_to,
                "application_assigned",
                "New application assignment",
                f"{entity_name} was assigned to you {assignment_source}.",
                "new_assignee",
            )
        )

    if previous_assignee:
        if assigned_to:
            message = (
                f"{entity_name} was reassigned from you to {assigned_to['name']} "
                f"by {actor_name}."
            )
        else:
            message = f"{entity_name} was unassigned from you by {actor_name}."

        notification_specs.append(
            (
                previous_assignee,
                "application_unassigned",
                "Application assignment removed",
                message,
                "previous_assignee",
            )
        )

    created = []
    seen_recipients = set()
    for recipient, notification_type, subject, message, audience in notification_specs:
        recipient_key = (str(recipient["id"]), recipient["user_type"])
        if recipient_key in seen_recipients:
            continue
        seen_recipients.add(recipient_key)

        metadata = {**base_metadata, "audience": audience}
        try:
            created.append(
                _create_notification(
                    recipient=recipient,
                    notification_type=notification_type,
                    subject=subject,
                    message=message,
                    metadata=metadata,
                    related_type=related_type,
                    related_id=related_id,
                    occurred_at=occurred_at,
                )
            )
        except Exception:
            logger.exception(
                "Failed to create %s notification for %s",
                event_type,
                recipient["id"],
            )

    return created
