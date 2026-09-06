from django.test import override_settings


@override_settings(
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:5173"],
    CORS_ALLOW_CREDENTIALS=True,
)
def test_staff_payment_preflight_allows_idempotency_key(client):
    response = client.options(
        "/api/loans/officer/payments/",
        HTTP_ORIGIN="http://127.0.0.1:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,idempotency-key",
    )

    assert response.status_code == 200
    allowed_headers = {
        value.strip().lower()
        for value in response["Access-Control-Allow-Headers"].split(",")
    }
    assert "idempotency-key" in allowed_headers


@override_settings(
    CORS_ALLOWED_ORIGINS=["http://127.0.0.1:5173"],
    CORS_ALLOW_CREDENTIALS=True,
    CORS_EXPOSE_HEADERS=(
        "content-disposition",
        "x-export-row-count",
        "x-export-max-rows",
    ),
)
def test_staff_export_headers_are_visible_to_the_web_client(client):
    response = client.options(
        "/api/loans/officer/schedules/export/",
        HTTP_ORIGIN="http://127.0.0.1:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    )

    assert response.status_code == 200
    exposed_headers = {
        value.strip().lower()
        for value in response["Access-Control-Expose-Headers"].split(",")
    }
    assert {
        "content-disposition",
        "x-export-row-count",
        "x-export-max-rows",
    } <= exposed_headers
