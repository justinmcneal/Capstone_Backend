"""
RepaymentSchedule Model - Loan repayment installments.
"""

from copy import deepcopy

from dateutil.relativedelta import relativedelta
from django.conf import settings

from config.field_encryption import decrypt_fields, encrypt_fields, encrypt_value
from loans.utils.money import from_centavos, rate_amount_centavos, to_centavos

from loans.utils.time import utcnow


def get_db():
    return settings.MONGODB


INSTALLMENT_STATUSES = [
    "pending",
    "partial",
    "overdue",
    "partial_overdue",
    "paid",
]
SCHEDULE_STATUSES = ["active", "paid_off", "restructured", "written_off"]


class RepaymentSchedule:
    """
    Repayment schedule for disbursed loans.
    """

    collection_name = "repayment_schedules"
    encrypted_fields = ("installments",)

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.loan_id = kwargs.get("loan_id")
        self.customer_id = kwargs.get("customer_id")

        # Schedule details
        self.principal = kwargs.get("principal", 0)
        self.interest_rate = kwargs.get("interest_rate", 0)  # Monthly rate
        self.term_months = kwargs.get("term_months", 12)
        self.monthly_payment = kwargs.get("monthly_payment", 0)
        self.total_amount = kwargs.get("total_amount", 0)
        self.total_interest = kwargs.get("total_interest", 0)
        self.principal_centavos = kwargs.get(
            "principal_centavos", to_centavos(self.principal, "principal")
        )
        self.monthly_payment_centavos = kwargs.get(
            "monthly_payment_centavos",
            to_centavos(self.monthly_payment, "monthly_payment"),
        )
        self.total_amount_centavos = kwargs.get(
            "total_amount_centavos", to_centavos(self.total_amount, "total_amount")
        )
        self.total_interest_centavos = kwargs.get(
            "total_interest_centavos",
            to_centavos(self.total_interest, "total_interest"),
        )
        self.status = kwargs.get("status", "active")
        self.paid_off_at = kwargs.get("paid_off_at")

        # Installments list
        self.installments = kwargs.get("installments", [])

        # Timestamps
        self.start_date = kwargs.get("start_date", utcnow())
        self.created_at = kwargs.get("created_at", utcnow())

        # Blockchain sync tracking
        self.blockchain_schedule_tx = kwargs.get("blockchain_schedule_tx", "")
        self.blockchain_overdue_tx = kwargs.get("blockchain_overdue_tx", {})
        self.blockchain_penalty_tx = kwargs.get("blockchain_penalty_tx", {})
        self.applied_payment_tokens = kwargs.get("applied_payment_tokens", [])
        self.accounting_version = int(kwargs.get("accounting_version", 0) or 0)

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "loan_id": self.loan_id,
            "customer_id": self.customer_id,
            "principal": self.principal,
            "interest_rate": self.interest_rate,
            "term_months": self.term_months,
            "monthly_payment": self.monthly_payment,
            "total_amount": self.total_amount,
            "total_interest": self.total_interest,
            "principal_centavos": self.principal_centavos,
            "monthly_payment_centavos": self.monthly_payment_centavos,
            "total_amount_centavos": self.total_amount_centavos,
            "total_interest_centavos": self.total_interest_centavos,
            "status": self.status,
            "paid_off_at": self.paid_off_at,
            "installments": self.installments,
            "start_date": self.start_date,
            "created_at": self.created_at,
            "blockchain_schedule_tx": self.blockchain_schedule_tx,
            "blockchain_overdue_tx": self.blockchain_overdue_tx,
            "blockchain_penalty_tx": self.blockchain_penalty_tx,
            "applied_payment_tokens": self.applied_payment_tokens,
            "accounting_version": self.accounting_version,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_dict()

        if self._id:
            # MongoDB's _id field is immutable and cannot be included in $set.
            data.pop("_id", None)
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    @classmethod
    def generate_for_loan(cls, loan_application, product):
        """
        Generate repayment schedule for a disbursed loan.

        Args:
            loan_application: LoanApplication instance
            product: LoanProduct instance

        Returns:
            RepaymentSchedule instance
        """
        principal = (
            loan_application.disbursed_amount or loan_application.approved_amount
        )
        interest_rate = product.interest_rate  # Monthly rate
        term_months = loan_application.term_months
        if not isinstance(term_months, int) or term_months < 1:
            raise ValueError("term_months must be a positive integer")

        principal_centavos = to_centavos(principal, "principal")
        monthly_interest_centavos = rate_amount_centavos(
            principal_centavos, interest_rate
        )
        total_interest_centavos = monthly_interest_centavos * term_months
        regular_principal_centavos, principal_remainder = divmod(
            principal_centavos, term_months
        )

        # Generate installments
        installments = []
        start_date = loan_application.disbursed_at or utcnow()

        for i in range(1, term_months + 1):
            due_date = start_date + relativedelta(months=i)
            principal_part_centavos = regular_principal_centavos
            if i == term_months:
                principal_part_centavos += principal_remainder
            installment_total_centavos = (
                principal_part_centavos + monthly_interest_centavos
            )
            installments.append(
                {
                    "number": i,
                    "due_date": due_date,
                    "principal": from_centavos(principal_part_centavos),
                    "principal_centavos": principal_part_centavos,
                    "interest": from_centavos(monthly_interest_centavos),
                    "interest_centavos": monthly_interest_centavos,
                    "total_amount": from_centavos(installment_total_centavos),
                    "total_amount_centavos": installment_total_centavos,
                    "status": "pending",
                    "paid_amount": 0,
                    "paid_amount_centavos": 0,
                    "paid_at": None,
                    "penalty_status": None,
                    "penalty_amount": 0,
                    "penalty_amount_centavos": 0,
                    "penalty_reason": "",
                    "penalty_applied_at": None,
                    "penalty_applied_by": None,
                    "penalty_waived_at": None,
                    "penalty_waived_by": None,
                    "penalty_waived_reason": "",
                }
            )

        schedule = cls(
            loan_id=loan_application.id,
            customer_id=loan_application.customer_id,
            principal=from_centavos(principal_centavos),
            principal_centavos=principal_centavos,
            interest_rate=interest_rate,
            term_months=term_months,
            monthly_payment=from_centavos(installments[0]["total_amount_centavos"]),
            monthly_payment_centavos=installments[0]["total_amount_centavos"],
            total_amount=from_centavos(principal_centavos + total_interest_centavos),
            total_amount_centavos=principal_centavos + total_interest_centavos,
            total_interest=from_centavos(total_interest_centavos),
            total_interest_centavos=total_interest_centavos,
            installments=installments,
            start_date=start_date,
        )
        return schedule.save()

    @staticmethod
    def _centavos(installment, field):
        centavo_field = f"{field}_centavos"
        if centavo_field in installment:
            return int(installment.get(centavo_field) or 0)
        return to_centavos(installment.get(field, 0) or 0, field)

    @classmethod
    def _required_centavos(cls, installment):
        required = cls._centavos(installment, "total_amount")
        if installment.get("penalty_status") == "applied":
            required += cls._centavos(installment, "penalty_amount")
        return required

    @classmethod
    def _normalized_unpaid_status(cls, installment, as_of=None):
        paid_centavos = cls._centavos(installment, "paid_amount")
        partial = paid_centavos > 0
        due_date = installment.get("due_date")
        as_of = as_of or utcnow()
        overdue = bool(
            due_date and hasattr(due_date, "date") and due_date.date() < as_of.date()
        )
        if overdue:
            return "partial_overdue" if partial else "overdue"
        return "partial" if partial else "pending"

    @classmethod
    def _normalize_installment(cls, installment, as_of=None):
        required = cls._required_centavos(installment)
        paid = min(cls._centavos(installment, "paid_amount"), required)
        installment["paid_amount_centavos"] = paid
        installment["paid_amount"] = from_centavos(paid)
        if paid >= required:
            installment["status"] = "paid"
            installment["paid_at"] = installment.get("paid_at") or utcnow()
        else:
            installment["status"] = cls._normalized_unpaid_status(installment, as_of)
            installment["paid_at"] = None
        return installment

    def get_next_payment(self):
        """Get the earliest unpaid installment, including partial/overdue states."""
        for inst in self.installments:
            if inst.get("status") != "paid":
                return inst
        return None

    def get_paid_count(self):
        """Count paid installments"""
        return sum(1 for inst in self.installments if inst["status"] == "paid")

    def get_remaining_balance(self):
        """Calculate exact remaining balance from per-installment centavos."""
        remaining = sum(
            max(
                self._required_centavos(inst) - self._centavos(inst, "paid_amount"),
                0,
            )
            for inst in self.installments
        )
        return from_centavos(remaining)

    def get_remaining_balance_centavos(self):
        return sum(
            max(
                self._required_centavos(inst) - self._centavos(inst, "paid_amount"),
                0,
            )
            for inst in self.installments
        )

    def is_paid_off(self):
        return self.get_remaining_balance_centavos() == 0

    def get_early_payoff_amount(self):
        """Return the exact current payoff amount, including applied penalties."""
        return self.get_remaining_balance()

    def get_installment(self, installment_number):
        """Get a specific installment by number"""
        for inst in self.installments:
            if inst["number"] == installment_number:
                return inst
        return None

    def is_installment_paid(self, installment_number):
        """Check if an installment is fully paid"""
        inst = self.get_installment(installment_number)
        return inst and inst.get("status") == "paid"

    def get_installment_remaining(self, installment_number):
        """Get remaining amount for a specific installment including penalties"""
        inst = self.get_installment(installment_number)
        if not inst:
            return None

        remaining = max(
            self._required_centavos(inst) - self._centavos(inst, "paid_amount"),
            0,
        )
        return from_centavos(remaining)

    def count_unpaid_before(self, installment_number):
        """Count unpaid installments before the given number"""
        count = 0
        for inst in self.installments:
            if inst["number"] < installment_number and inst.get("status") != "paid":
                count += 1
        return count

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find_by_loan(cls, loan_id):
        return cls.find_one({"loan_id": str(loan_id)})

    @classmethod
    def find_by_customer(cls, customer_id):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({"customer_id": str(customer_id)})
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def find_all(cls):
        db = get_db()
        collection = db[cls.collection_name]
        docs = collection.find({})
        return [cls.from_dict(doc) for doc in docs]

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("loan_id", unique=True)
        collection.create_index("customer_id")

    @classmethod
    def update_blockchain_schedule_tx(cls, schedule_id, tx_hash):
        db = get_db()
        collection = db[cls.collection_name]
        collection.update_one(
            {"_id": schedule_id},
            {"$set": {"blockchain_schedule_tx": tx_hash}},
        )

    @classmethod
    def update_blockchain_overdue_tx(cls, schedule_id, installment_number, tx_hash):
        db = get_db()
        collection = db[cls.collection_name]
        field = f"blockchain_overdue_tx.{installment_number}"
        collection.update_one(
            {"_id": schedule_id},
            {"$set": {field: tx_hash}},
        )

    @classmethod
    def update_blockchain_penalty_tx(
        cls, schedule_id, installment_number, action, tx_hash
    ):
        db = get_db()
        collection = db[cls.collection_name]
        field = f"blockchain_penalty_tx.{installment_number}.{action}"
        collection.update_one(
            {"_id": schedule_id},
            {"$set": {field: tx_hash}},
        )

    def record_payment(self, installment_number, amount):
        """
        Record a payment against an installment.

        Returns:
            Updated installment or None if not found
        """
        for i, inst in enumerate(self.installments):
            if inst["number"] == installment_number:
                amount_centavos = to_centavos(amount)
                if amount_centavos <= 0:
                    raise ValueError("amount must be greater than 0")
                required = self._required_centavos(inst)
                paid = self._centavos(inst, "paid_amount")
                if amount_centavos > required - paid:
                    raise ValueError(
                        "Amount exceeds remaining balance of "
                        f"PHP{from_centavos(required - paid):.2f}"
                    )
                new_paid = paid + amount_centavos
                inst["paid_amount_centavos"] = new_paid
                inst["paid_amount"] = from_centavos(new_paid)
                self._normalize_installment(inst)

                self.installments[i] = inst
                self._mark_paid_off_if_complete()
                self.save()
                return inst
        return None

    def _mark_paid_off_if_complete(self):
        if self.is_paid_off():
            self.status = "paid_off"
            self.paid_off_at = self.paid_off_at or utcnow()
        elif self.status == "paid_off":
            self.status = "active"
            self.paid_off_at = None

    def apply_payment_atomic(self, installment_number, amount, payment_token):
        """Apply one payment with optimistic concurrency and replay protection.

        The payment token is stored on the installment in the same atomic update
        as the balance mutation. A retry after an interrupted request can therefore
        detect that the schedule was already updated without applying it twice.
        """
        db = get_db()
        collection = db[self.collection_name]

        for _attempt in range(3):
            current = self.find_one({"_id": self._id})
            if not current:
                raise ValueError("Repayment schedule not found")

            installment = current.get_installment(installment_number)
            if not installment:
                raise ValueError(f"Installment #{installment_number} not found")

            if payment_token in current.applied_payment_tokens:
                self.__dict__.update(current.__dict__)
                return installment, True

            if installment.get("status") == "paid":
                raise ValueError(
                    f"Installment #{installment_number} is already fully paid"
                )

            amount_centavos = to_centavos(amount)
            if amount_centavos <= 0:
                raise ValueError("amount must be greater than 0")
            paid_centavos = current._centavos(installment, "paid_amount")
            required_centavos = current._required_centavos(installment)
            remaining_centavos = required_centavos - paid_centavos
            if amount_centavos > remaining_centavos:
                raise ValueError(
                    "Amount exceeds remaining balance of "
                    f"PHP{from_centavos(remaining_centavos):.2f}"
                )

            new_paid_centavos = paid_centavos + amount_centavos
            updated_installments = deepcopy(current.installments)
            updated_installment = next(
                item
                for item in updated_installments
                if item["number"] == installment_number
            )
            updated_installment["paid_amount_centavos"] = new_paid_centavos
            updated_installment["paid_amount"] = from_centavos(new_paid_centavos)
            current._normalize_installment(updated_installment)
            paid_off = all(
                current._centavos(item, "paid_amount")
                >= current._required_centavos(item)
                for item in updated_installments
            )
            schedule_updates = {"installments": encrypt_value(updated_installments)}
            if paid_off:
                schedule_updates.update({"status": "paid_off", "paid_off_at": utcnow()})

            version_filter = {"accounting_version": current.accounting_version}
            if current.accounting_version == 0:
                # Schedules created before accounting_version was introduced
                # have no field. This match initializes it for later writes.
                version_filter = {
                    "$or": [
                        {"accounting_version": 0},
                        {"accounting_version": {"$exists": False}},
                    ]
                }

            result = collection.update_one(
                {
                    "_id": self._id,
                    "applied_payment_tokens": {"$ne": payment_token},
                    **version_filter,
                },
                {
                    "$set": schedule_updates,
                    "$addToSet": {"applied_payment_tokens": payment_token},
                    "$inc": {"accounting_version": 1},
                },
            )
            if result.modified_count:
                updated = self.find_one({"_id": self._id})
                self.__dict__.update(updated.__dict__)
                return updated.get_installment(installment_number), False

        raise RuntimeError("Payment could not be applied due to a concurrent update")

    def mark_overdue_installments(self, as_of=None):
        """
        Mark pending/partial installments as overdue when past due date.

        Returns:
            list of installment numbers updated
        """
        if as_of is None:
            as_of = utcnow()

        updated = []
        for i, inst in enumerate(self.installments):
            due_date = inst.get("due_date")
            status = inst.get("status", "pending")
            if status not in {"pending", "partial", "overdue", "partial_overdue"}:
                continue
            if not due_date or not hasattr(due_date, "date"):
                continue
            normalized_status = self._normalized_unpaid_status(inst, as_of)
            if (
                normalized_status in {"overdue", "partial_overdue"}
                and status != normalized_status
            ):
                inst["status"] = normalized_status
                inst["overdue_at"] = as_of
                self.installments[i] = inst
                updated.append(inst.get("number"))

        if updated:
            self.save()

        return updated

    def apply_penalty(self, installment_number, amount, reason, actor_id):
        installment = self.get_installment(installment_number)
        if not installment:
            raise ValueError(f"Installment #{installment_number} not found")
        if installment.get("status") == "paid":
            raise ValueError(f"Installment #{installment_number} is already paid")
        if installment.get("penalty_status") == "applied":
            raise ValueError(
                f"Penalty already applied for installment #{installment_number}"
            )
        penalty_centavos = to_centavos(amount, "penalty_amount")
        if penalty_centavos <= 0:
            raise ValueError("penalty_amount must be greater than 0")
        now = utcnow()
        installment.update(
            {
                "penalty_status": "applied",
                "penalty_amount_centavos": penalty_centavos,
                "penalty_amount": from_centavos(penalty_centavos),
                "penalty_reason": reason,
                "penalty_applied_at": now,
                "penalty_applied_by": str(actor_id),
                "penalty_waived_at": None,
                "penalty_waived_by": None,
                "penalty_waived_reason": "",
            }
        )
        self._normalize_installment(installment)
        self._mark_paid_off_if_complete()
        self.save()
        return installment

    def waive_penalty(self, installment_number, reason, actor_id):
        installment = self.get_installment(installment_number)
        if not installment:
            raise ValueError(f"Installment #{installment_number} not found")
        if installment.get("penalty_status") != "applied":
            raise ValueError(
                f"No applied penalty found for installment #{installment_number}"
            )
        now = utcnow()
        base_required = self._centavos(installment, "total_amount")
        paid = self._centavos(installment, "paid_amount")
        credit = max(paid - base_required, 0)
        if credit:
            installment["paid_amount_centavos"] = base_required
            installment["paid_amount"] = from_centavos(base_required)
            installment["waiver_credit_centavos"] = credit
            installment["waiver_credit_amount"] = from_centavos(credit)
        installment.update(
            {
                "penalty_status": "waived",
                "penalty_waived_at": now,
                "penalty_waived_by": str(actor_id),
                "penalty_waived_reason": reason,
            }
        )
        self._normalize_installment(installment)
        self._mark_paid_off_if_complete()
        self.save()
        return installment

    def apply_early_payoff_atomic(self, amount, payment_token):
        """Apply one exact payoff across every open installment atomically."""
        collection = get_db()[self.collection_name]
        for _attempt in range(3):
            current = self.find_one({"_id": self._id})
            if not current:
                raise ValueError("Repayment schedule not found")
            if payment_token in current.applied_payment_tokens:
                self.__dict__.update(current.__dict__)
                return [], True

            amount_centavos = to_centavos(amount)
            expected_centavos = current.get_remaining_balance_centavos()
            if amount_centavos != expected_centavos:
                raise ValueError(
                    "Early payoff amount must equal the current payoff quote of "
                    f"PHP{from_centavos(expected_centavos):.2f}"
                )
            if expected_centavos <= 0:
                raise ValueError("Loan is already paid off")

            updated_installments = deepcopy(current.installments)
            allocations = []
            for installment in updated_installments:
                remaining = max(
                    current._required_centavos(installment)
                    - current._centavos(installment, "paid_amount"),
                    0,
                )
                if not remaining:
                    continue
                new_paid = current._centavos(installment, "paid_amount") + remaining
                installment["paid_amount_centavos"] = new_paid
                installment["paid_amount"] = from_centavos(new_paid)
                current._normalize_installment(installment)
                allocations.append(
                    {
                        "installment_number": installment["number"],
                        "amount_centavos": remaining,
                        "amount": from_centavos(remaining),
                    }
                )

            now = utcnow()
            version_filter = {"accounting_version": current.accounting_version}
            if current.accounting_version == 0:
                # Schedules created before accounting_version was introduced
                # have no field. This match initializes it for later writes.
                version_filter = {
                    "$or": [
                        {"accounting_version": 0},
                        {"accounting_version": {"$exists": False}},
                    ]
                }
            result = collection.update_one(
                {
                    "_id": self._id,
                    "applied_payment_tokens": {"$ne": payment_token},
                    **version_filter,
                },
                {
                    "$set": {
                        "installments": encrypt_value(updated_installments),
                        "status": "paid_off",
                        "paid_off_at": now,
                    },
                    "$addToSet": {"applied_payment_tokens": payment_token},
                    "$inc": {"accounting_version": 1},
                },
            )
            if result.modified_count:
                updated = self.find_one({"_id": self._id})
                self.__dict__.update(updated.__dict__)
                return allocations, False
        raise RuntimeError("Payoff could not be applied due to a concurrent update")
