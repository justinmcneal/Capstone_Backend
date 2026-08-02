"""Bounded read queries shared by customer and officer payment views."""

from loans.models import LoanPayment


def payment_history_page(loan_id, page=1, page_size=50):
    query = {"loan_id": str(loan_id)}
    total = LoanPayment.count(query)
    payments = LoanPayment.find(
        query,
        sort=[("recorded_at", -1)],
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "payments": payments,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "total_paid": LoanPayment.get_total_paid(loan_id),
    }
