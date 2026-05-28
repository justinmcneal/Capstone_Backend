from datetime import datetime
from bson import ObjectId
from accounts.models.consent import Consent
import logging

logger = logging.getLogger("consent")


class ConsentService:
    """
    Service for managing user consent for data collection and AI features.

    This service handles:
    - Creating consent records
    - Updating consent preferences
    - Checking consent status for AI feature access
    """

    @staticmethod
    def get_or_create_consent(user_id, user_type="customer"):
        """
        Get existing consent record or create a new one.

        Args:
            user_id: The user's ObjectId (string or ObjectId)
            user_type: Type of user ('customer' or 'loan_officer')

        Returns:
            Consent instance
        """
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)

        consent = Consent.find_by_user(user_id, user_type)

        if not consent:
            consent = Consent(
                user_id=user_id,
                user_type=user_type,
                data_consent=False,
                ai_consent=False,
            )
            consent.save()
            logger.info(f"Created new consent record for user {user_id}")

        return consent

    @staticmethod
    def record_consent(user_id, user_type, data_consent, ai_consent, ip_address=""):
        """
        Record initial consent from user.

        Args:
            user_id: The user's ObjectId
            user_type: Type of user
            data_consent: Whether user consents to data collection
            ai_consent: Whether user consents to AI features
            ip_address: IP address for audit logging

        Returns:
            Consent instance
        """
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)

        # Check if consent already exists
        existing = Consent.find_by_user(user_id, user_type)

        if existing:
            # Update existing consent
            existing.data_consent = data_consent
            existing.ai_consent = ai_consent
            existing.ip_address = ip_address
            existing.save()
            logger.info(
                f"Updated consent for user {user_id}: data={data_consent}, ai={ai_consent}"
            )
            return existing

        # Create new consent
        consent = Consent(
            user_id=user_id,
            user_type=user_type,
            data_consent=data_consent,
            ai_consent=ai_consent,
            ip_address=ip_address,
            consent_date=datetime.utcnow() if (data_consent or ai_consent) else None,
        )
        consent.save()
        logger.info(
            f"Recorded consent for user {user_id}: data={data_consent}, ai={ai_consent}"
        )

        return consent

    @staticmethod
    def update_consent(user_id, user_type, updates, ip_address=""):
        """
        Update user's consent preferences.

        Args:
            user_id: The user's ObjectId
            user_type: Type of user
            updates: Dictionary with consent updates
            ip_address: IP address for audit logging

        Returns:
            Consent instance

        Raises:
            ValueError: If no consent record exists
        """
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)

        consent = Consent.find_by_user(user_id, user_type)

        if not consent:
            raise ValueError("No consent record found for user")

        # Track what changed for logging
        changes = {}

        if "data_consent" in updates:
            old_value = consent.data_consent
            consent.data_consent = updates["data_consent"]
            if old_value != consent.data_consent:
                changes["data_consent"] = {
                    "from": old_value,
                    "to": consent.data_consent,
                }

        if "ai_consent" in updates:
            old_value = consent.ai_consent
            consent.ai_consent = updates["ai_consent"]
            if old_value != consent.ai_consent:
                changes["ai_consent"] = {"from": old_value, "to": consent.ai_consent}

        consent.ip_address = ip_address
        consent.save()

        if changes:
            logger.info(f"Consent updated for user {user_id}: {changes}")

        return consent

    @staticmethod
    def check_ai_consent(user_id, user_type="customer"):
        """
        Check if user has given AI consent.

        Args:
            user_id: The user's ObjectId
            user_type: Type of user

        Returns:
            bool: True if AI consent is given, False otherwise
        """
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)

        consent = Consent.find_by_user(user_id, user_type)

        if not consent:
            return False

        return consent.can_access_ai

    @staticmethod
    def check_data_consent(user_id, user_type="customer"):
        """
        Check if user has given data consent.

        Args:
            user_id: The user's ObjectId
            user_type: Type of user

        Returns:
            bool: True if data consent is given, False otherwise
        """
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)

        consent = Consent.find_by_user(user_id, user_type)

        if not consent:
            return False

        return consent.can_access_data_features

    @staticmethod
    def get_consent_status(user_id, user_type="customer"):
        """
        Get full consent status for a user.

        Args:
            user_id: The user's ObjectId
            user_type: Type of user

        Returns:
            dict: Consent status information
        """
        if isinstance(user_id, str):
            user_id = ObjectId(user_id)

        consent = Consent.find_by_user(user_id, user_type)

        if not consent:
            return {
                "data_consent": False,
                "ai_consent": False,
                "consent_date": None,
                "updated_at": None,
                "can_access_ai": False,
                "has_consent_record": False,
            }

        return {
            "data_consent": consent.data_consent,
            "ai_consent": consent.ai_consent,
            "consent_date": consent.consent_date,
            "updated_at": consent.updated_at,
            "can_access_ai": consent.can_access_ai,
            "has_consent_record": True,
        }
