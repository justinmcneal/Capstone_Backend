"""Accounts-domain adapter for the central durable audit writer."""

from analytics.services.audit_writer import record_audit


def record_account_audit(**kwargs):
    return record_audit(domain="accounts", **kwargs)
