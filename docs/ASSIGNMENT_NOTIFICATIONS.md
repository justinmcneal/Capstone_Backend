# Assignment Notifications

## Scope

Loan applications remain assigned to loan officers through the existing
`assigned_officer` field. Admins perform manual assignment and reassignment;
they are not application assignees.

Admin-as-assignee support was intentionally not added because application
queries, officer workload calculations, review authorization, and dashboards
all treat `assigned_officer` as a loan-officer identifier. Supporting both
roles requires a separate role-aware assignment model and API contract.

## Events and recipients

The loan assignment service publishes events only after the application has
been saved successfully.

| Change | Assigner | New officer | Previous officer |
| --- | --- | --- | --- |
| Initial assignment | Confirmation | Assigned to you | — |
| Reassignment | Reassignment confirmation | Assigned to you | Reassigned from you |
| Unassignment template | Confirmation | — | Unassigned from you |

Automatic assignment has no admin recipient. The assigned officer receives an
"assigned automatically" message.

Superadmins receive a personal assignment notification only when that
Superadmin is the authenticated `assigned_by` actor. Assignment events are not
copied to other Superadmins; system-wide oversight belongs in the audit log,
not the personal notification inbox.

Notification types:

- `application_assigned`
- `application_reassigned`
- `application_unassigned`

All records use `channel: in_app`, `related_type: loan`, and the loan
application ID as `related_id`. Persistence is synchronous so an accepted
assignment reliably creates inbox records. WebSocket broadcast is best-effort
and uses the existing notification channel layer. Assignment events do not
send email or mobile push notifications.

## Notification document extension

Existing documents remain valid. Assignment notifications add an optional
`metadata` object:

```json
{
  "event_type": "application_reassigned",
  "audience": "previous_assignee",
  "assigned_by": {"id": "...", "user_type": "admin", "name": "..."},
  "assigned_to": {"id": "...", "user_type": "loan_officer", "name": "..."},
  "previous_assignee": {
    "id": "...",
    "user_type": "loan_officer",
    "name": "..."
  },
  "entity": {"id": "...", "type": "loan_application", "name": "..."},
  "occurred_at": "2026-07-22T00:00:00+00:00"
}
```

The normal `created_at` field is still the canonical inbox timestamp.
`occurred_at` makes the shared event timestamp explicit across all documents
created for the same change.

## Extending assignment events

Call `publish_assignment_notifications` from a domain service after its
assignment update succeeds. Supply dictionaries for the actor, new assignee,
and previous assignee using `id`, `user_type`, `name`, and optional `email`,
plus the domain entity name/type/reference. The shared publisher owns message
selection, persistence, and WebSocket broadcast; domain services remain
responsible for authorization and changing the assigned field.

For a future role-aware assignee model, introduce an assignee type alongside
the assignee ID and update access-control queries before allowing admins,
branches, or teams to be selected.
