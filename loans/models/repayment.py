"""
RepaymentSchedule Model - Loan repayment installments.
"""

from copy import deepcopy

from dateutil.relativedelta import relativedelta
from django.conf import settings

from config.field_encryption import decrypt_fields, encrypt_fields

from loans.utils.time import utcnow


def get_db():
    return settings.MONGODB


INSTALLMENT_STATUSES = ["pending", "paid", "overdue", "partial"]


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
            "installments": self.installments,
            "start_date": self.start_date,
            "created_at": self.created_at,
            "blockchain_schedule_tx": self.blockchain_schedule_tx,
            "blockchain_overdue_tx": self.blockchain_overdue_tx,
            "blockchain_penalty_tx": self.blockchain_penalty_tx,
            "applied_payment_tokens": self.applied_payment_tokens,
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

    def update_blockchain_schedule_tx(self, tx_hash):
        """Update the blockchain schedule transaction hash."""
        self.blockchain_schedule_tx = tx_hash
        return self.save()

    def update_blockchain_overdue_tx(self, installment_number, tx_hash):
        """Record an overdue marking transaction hash."""
        self.blockchain_overdue_tx = dict(self.blockchain_overdue_tx or {})
        self.blockchain_overdue_tx[str(installment_number)] = tx_hash
        return self.save()

    def update_blockchain_penalty_tx(self, installment_number, action, tx_hash):
        """Record a penalty apply/waive transaction hash."""
        self.blockchain_penalty_tx = dict(self.blockchain_penalty_tx or {})
        self.blockchain_penalty_tx[str(installment_number)][action] = tx_hash
        return self.save()

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

        # Calculate monthly interest
        monthly_interest = principal * interest_rate
        total_interest = monthly_interest * term_months

        # Monthly principal portion
        monthly_principal = principal / term_months

        # Total monthly payment
        monthly_payment = monthly_principal + monthly_interest
        total_amount = principal + total_interest

        # Generate installments
        installments = []
        start_date = loan_application.disbursed_at or utcnow()

        for i in range(1, term_months + 1):
            due_date = start_date + relativedelta(months=i)
            installments.append(
                {
                    "number": i,
                    "due_date": due_date,
                    "principal": round(monthly_principal, 2),
                    "interest": round(monthly_interest, 2),
                    "total_amount": round(monthly_payment, 2),
                    "status": "pending",
                    "paid_amount": 0,
                    "paid_at": None,
                    "penalty_status": None,
                    "penalty_amount": 0,
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
            principal=principal,
            interest_rate=interest_rate,
            term_months=term_months,
            monthly_payment=round(monthly_payment, 2),
            total_amount=round(total_amount, 2),
            total_interest=round(total_interest, 2),
            installments=installments,
            start_date=start_date,
        )
        return schedule.save()

    def get_next_payment(self):
        """Get next pending installment"""
        for inst in self.installments:
            if inst["status"] == "pending":
                return inst
        return None

    def get_paid_count(self):
        """Count paid installments"""
        return sum(1 for inst in self.installments if inst["status"] == "paid")

    def get_remaining_balance(self):
        """Calculate remaining balance including unpaid penalties"""
        paid = sum(inst.get("paid_amount", 0) for inst in self.installments)
        
        # Include unpaid penalties in the remaining balance
        unpaid_penalties = sum(
            inst.get("penalty_amount", 0) 
            for inst in self.installments 
            if inst.get("penalty_status") == "applied" and inst.get("status") != "paid"
        )
        
        # Never return negative values even if historical overpayments exist.
        return max(self.total_amount + unpaid_penalties - paid, 0)

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
        
        base_remaining = inst["total_amount"] - inst.get("paid_amount", 0)
        
        # Add penalty if applied and not waived
        penalty_amount = 0
        if inst.get("penalty_status") == "applied":
            penalty_amount = inst.get("penalty_amount", 0)
        
        return base_remaining + penalty_amount

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
    def update_blockchain_penalty_tx(cls, schedule_id, installment_number, action, tx_hash):
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
                new_paid_amount = inst.get("paid_amount", 0) + amount

                # Calculate actual amount required including penalties
                actual_total_amount = inst["total_amount"]
                if inst.get("penalty_status") == "applied":
                    actual_total_amount += inst.get("penalty_amount", 0)

                # Update status based on payment
                if new_paid_amount >= actual_total_amount:
                    inst["paid_amount"] = actual_total_amount
                    inst["status"] = "paid"
                    inst["paid_at"] = utcnow()
                elif new_paid_amount > 0:
                    inst["paid_amount"] = new_paid_amount
                    inst["status"] = "partial"

                self.installments[i] = inst
                self.save()
                return inst
        return None

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
                raise ValueError(f"Installment #{installment_number} is already fully paid")

            paid_amount = installment.get("paid_amount", 0) or 0
            required_amount = installment["total_amount"]
            if installment.get("penalty_status") == "applied":
                required_amount += installment.get("penalty_amount", 0)
            remaining = required_amount - paid_amount
            if amount - remaining > 0.01:
                raise ValueError(
                    f"Amount exceeds remaining balance of PHP{remaining:.2f}"
                )

            new_paid_amount = min(paid_amount + amount, required_amount)
            new_status = "paid" if new_paid_amount >= required_amount else "partial"
            updated_installments = deepcopy(current.installments)
            updated_installment = next(
                item
                for item in updated_installments
                if item["number"] == installment_number
            )
            updated_installment["paid_amount"] = new_paid_amount
            updated_installment["status"] = new_status
            if new_status == "paid":
                updated_installment["paid_at"] = utcnow()

            result = collection.update_one(
                {
                    "_id": self._id,
                    "installments": current.installments,
                    "applied_payment_tokens": {"$ne": payment_token},
                },
                {
                    "$set": {"installments": updated_installments},
                    "$addToSet": {"applied_payment_tokens": payment_token},
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
            if status not in {"pending", "partial"}:
                continue
            if not due_date or not hasattr(due_date, "date"):
                continue
            if due_date.date() < as_of.date():
                inst["status"] = "overdue"
                inst["overdue_at"] = as_of
                self.installments[i] = inst
                updated.append(inst.get("number"))

        if updated:
            self.save()

        return updated
