import re

from bson import ObjectId

from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.email_utils import EmailUtils


ROLE_MODEL_MAP = {
    "customer": Customer,
    "loan_officer": LoanOfficer,
    "admin": Admin,
}


def _find_by_email(model, normalized_email):
    account = model.find_one({"email": normalized_email})
    if account:
        return account
    return model.find_one(
        {"email": re.compile(f"^{re.escape(normalized_email)}$", re.IGNORECASE)}
    )


def find_accounts_by_email(normalized_email):
    matches = {}
    for role, model in ROLE_MODEL_MAP.items():
        account = _find_by_email(model, normalized_email)
        if account:
            matches[role] = account
    return matches


def is_email_available_globally(normalized_email, *, exclude_role=None, exclude_id=None):
    for role, account in find_accounts_by_email(normalized_email).items():
        if exclude_role == role and exclude_id:
            account_id = str(getattr(account, "_id", "") or "")
            if account_id == str(exclude_id):
                continue
            if ObjectId.is_valid(str(exclude_id)) and account_id == str(
                ObjectId(str(exclude_id))
            ):
                continue
        return False
    return True


def assert_email_available_globally(email, *, exclude_role=None, exclude_id=None):
    normalized_email = EmailUtils.normalize_email(email)
    if not normalized_email:
        raise ValueError("Email is required")
    if not is_email_available_globally(
        normalized_email,
        exclude_role=exclude_role,
        exclude_id=exclude_id,
    ):
        raise ValueError("An account with this email already exists")
    return normalized_email
