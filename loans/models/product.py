"""
LoanProduct Model - Admin managed loan products catalog.
"""

from bson import ObjectId
from django.conf import settings

from loans.utils.time import utcnow


def get_db():
    return settings.MONGODB


class LoanProduct:
    """
    Loan product catalog - managed by Admins.
    """

    collection_name = "loan_products"

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")

        # Product info
        self.name = kwargs.get("name", "")  # "Micro Business Loan"
        self.code = kwargs.get("code", "")  # "MBL001"
        self.description = kwargs.get("description", "")

        # Loan parameters
        self.min_amount = kwargs.get("min_amount", 5000)  # PHP
        self.max_amount = kwargs.get("max_amount", 50000)
        self.interest_rate = kwargs.get("interest_rate", 0.015)  # Monthly rate (1.5%)
        self.min_term_months = kwargs.get("min_term_months", 3)
        self.max_term_months = kwargs.get("max_term_months", 24)

        # Requirements
        self.required_documents = kwargs.get("required_documents", ["valid_id"])
        self.min_business_months = kwargs.get("min_business_months", 6)
        self.min_monthly_income = kwargs.get("min_monthly_income", 5000)

        # Target category
        self.business_types = kwargs.get("business_types", [])  # Empty = all types
        self.target_description = kwargs.get("target_description", "")

        # Status
        self.active = kwargs.get("active", True)
        self.created_by = kwargs.get("created_by")  # Admin ID
        self.created_at = kwargs.get("created_at", utcnow())
        self.updated_at = kwargs.get("updated_at", utcnow())

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "min_amount": self.min_amount,
            "max_amount": self.max_amount,
            "interest_rate": self.interest_rate,
            "min_term_months": self.min_term_months,
            "max_term_months": self.max_term_months,
            "required_documents": self.required_documents,
            "min_business_months": self.min_business_months,
            "min_monthly_income": self.min_monthly_income,
            "business_types": self.business_types,
            "target_description": self.target_description,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**data)

    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        self.updated_at = utcnow()
        data = self.to_dict()

        if self._id:
            # Remove _id from the update data to avoid immutable field error
            update_data = {k: v for k, v in data.items() if k != "_id"}
            result = collection.update_one({"_id": self._id}, {"$set": update_data})
            if result.modified_count == 0 and result.matched_count == 0:
                raise ValueError(f"Product with id {self._id} not found in database")
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    def delete(self):
        """Soft delete - set inactive"""
        if not self._id:
            raise ValueError("Cannot delete product without id")
        self.active = False
        self.save()
        return True

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find(cls, query=None, active_only=True):
        db = get_db()
        collection = db[cls.collection_name]
        query = query or {}
        if active_only:
            query["active"] = True
        cursor = collection.find(query).sort("name", 1)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def find_by_id(cls, product_id):
        try:
            return cls.find_one({"_id": ObjectId(product_id)})
        except Exception:
            return None

    @classmethod
    def find_by_code(cls, code):
        return cls.find_one({"code": code})

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("code", unique=True)
        collection.create_index("active")
        collection.create_index("name")
