"""Bounded, server-authored audit log exports."""

import csv
import html
import io

from django.conf import settings
from django.http import HttpResponse

from analytics.models import AuditLog
from analytics.services.operations import bounded_cursor


class AuditExportLimitError(ValueError):
    """Raised when a filtered export exceeds the published server bound."""


def audit_export_max_rows() -> int:
    """Keep exports inside the same maximum window published by list APIs."""
    return int(getattr(settings, "ANALYTICS_MAX_PAGE_OFFSET", 10_000)) + 200


def collect_audit_export_rows(query, *, serializer):
    """Read one fixed query and fail instead of returning a partial export."""
    maximum = audit_export_max_rows()
    collection = settings.MONGODB[AuditLog.collection_name]
    cursor = (
        bounded_cursor(collection.find(query))
        .sort([("timestamp", -1), ("_id", -1)])
        .limit(maximum + 1)
    )
    documents = list(cursor)
    if len(documents) > maximum:
        raise AuditExportLimitError(
            f"This result contains more than {maximum:,} audit records. "
            "Narrow the filters before exporting."
        )
    return [serializer(AuditLog.from_dict(document)) for document in documents]


def _spreadsheet_safe(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def _csv_content(rows, columns) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([_spreadsheet_safe(row.get(key)) for key, _ in columns])
    return "\ufeff" + output.getvalue()


def _excel_compatible_content(rows, columns, *, snapshot_at) -> str:
    headings = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(_spreadsheet_safe(row.get(key)))}</td>"
            for key, _ in columns
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<!doctype html><html><head><meta charset="UTF-8"></head><body>'
        f"<p>Authoritative snapshot as of {html.escape(snapshot_at.isoformat())}</p>"
        f'<table border="1"><thead><tr>{headings}</tr></thead>'
        f"<tbody>{body}</tbody></table></body></html>"
    )


def build_audit_export_response(
    rows,
    *,
    export_format: str,
    filename_prefix: str,
    snapshot_at,
    include_actor_type: bool,
):
    columns = [
        ("id", "ID"),
        ("timestamp", "Timestamp"),
    ]
    if include_actor_type:
        columns.append(("actor_type", "Actor Type"))
    columns.extend(
        [
            ("action", "Action"),
            ("action_group", "Action Group"),
            ("resource_type", "Resource Type"),
            ("resource_id", "Resource ID"),
        ]
    )

    date_suffix = snapshot_at.date().isoformat()
    if export_format == "csv":
        content = _csv_content(rows, columns)
        content_type = "text/csv; charset=utf-8"
        extension = "csv"
    else:
        content = _excel_compatible_content(rows, columns, snapshot_at=snapshot_at)
        content_type = "application/vnd.ms-excel; charset=utf-8"
        extension = "xls"

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="{filename_prefix}-{date_suffix}.{extension}"'
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Audit-Snapshot-As-Of"] = snapshot_at.isoformat()
    response["X-Export-Row-Count"] = str(len(rows))
    response["X-Export-Max-Rows"] = str(audit_export_max_rows())
    return response
