"""Request outcome and latency metrics for the Loans API."""

from time import monotonic

from loans.metrics import LOAN_REQUEST_LATENCY, LOAN_REQUESTS, increment, observe


class LoanRequestMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _scope(path):
        parts = [part for part in str(path).split("/") if part]
        try:
            index = parts.index("loans")
        except ValueError:
            return None
        candidate = parts[index + 1] if len(parts) > index + 1 else "root"
        return (
            candidate
            if candidate in {"customer", "officer", "admin", "blockchain"}
            else "shared"
        )

    def __call__(self, request):
        scope = self._scope(request.path)
        if scope is None:
            return self.get_response(request)
        started = monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            increment(
                LOAN_REQUESTS, scope=scope, method=request.method, outcome="exception"
            )
            observe(
                LOAN_REQUEST_LATENCY,
                monotonic() - started,
                scope=scope,
                method=request.method,
            )
            raise
        outcome = (
            "success"
            if response.status_code < 400
            else "client_error" if response.status_code < 500 else "server_error"
        )
        increment(LOAN_REQUESTS, scope=scope, method=request.method, outcome=outcome)
        observe(
            LOAN_REQUEST_LATENCY,
            monotonic() - started,
            scope=scope,
            method=request.method,
        )
        return response
