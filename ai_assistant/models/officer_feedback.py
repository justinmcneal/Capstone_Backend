"""Officer-only ratings for AI review briefs.

Feedback records an officer's assessment of a generated brief. It never
stores brief content, prompts, or loan state — only the rating, an optional
short comment, and the linkage needed to join it back to the originating
request for quality review.
"""

from datetime import datetime, timezone

from django.conf import settings
from pymongo import ASCENDING

from config.field_encryption import decrypt_fields, encrypt_fields


class OfficerAIFeedback:
    """Rating store for loan-officer AI review briefs."""

    collection_name = 'officer_ai_feedback'
    encrypted_fields = ('comment',)
    allowed_ratings = frozenset({'up', 'down'})

    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.officer_id = kwargs.get('officer_id')
        self.application_id = kwargs.get('application_id')
        self.customer_id = kwargs.get('customer_id')
        self.request_id = kwargs.get('request_id')
        self.conversation_id = kwargs.get('conversation_id')
        self.language = kwargs.get('language', 'en')
        self.rating = kwargs.get('rating')
        self.comment = kwargs.get('comment', '')
        self.timestamp = kwargs.get('timestamp', datetime.now(timezone.utc))
        self.created_at = kwargs.get('created_at', datetime.now(timezone.utc))
        self.updated_at = kwargs.get('updated_at', datetime.now(timezone.utc))

    @classmethod
    def _collection(cls):
        return settings.MONGODB[cls.collection_name]

    def to_dict(self):
        data = {
            'officer_id': self.officer_id,
            'application_id': self.application_id,
            'customer_id': self.customer_id,
            'request_id': self.request_id,
            'conversation_id': self.conversation_id,
            'language': self.language,
            'rating': self.rating,
            'comment': self.comment,
            'timestamp': self.timestamp,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if self._id:
            data['_id'] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    @classmethod
    def record_feedback(
        cls,
        *,
        officer_id,
        application_id,
        customer_id,
        request_id,
        conversation_id,
        language,
        rating,
        comment,
    ):
        """Atomically create or replace one officer rating per brief request."""
        if rating not in cls.allowed_ratings:
            raise ValueError('Feedback rating must be up or down')
        now = datetime.now(timezone.utc)
        result = cls._collection().update_one(
            {
                'officer_id': str(officer_id),
                'application_id': str(application_id),
                'request_id': str(request_id),
            },
            {
                '$set': {
                    'customer_id': str(customer_id),
                    'conversation_id': (
                        str(conversation_id) if conversation_id else None
                    ),
                    'language': language,
                    'rating': rating,
                    'comment': encrypt_fields(
                        {'comment': str(comment or '')}, cls.encrypted_fields
                    )['comment'],
                    'timestamp': now,
                    'updated_at': now,
                },
                '$setOnInsert': {'created_at': now},
            },
            upsert=True,
        )
        return {'updated': bool(result.matched_count)}

    @classmethod
    def find_for_request(cls, officer_id, application_id, request_id):
        return cls.from_dict(
            cls._collection().find_one(
                {
                    'officer_id': str(officer_id),
                    'application_id': str(application_id),
                    'request_id': str(request_id),
                }
            )
        )

    @classmethod
    def create_indexes(cls):
        collection = cls._collection()
        collection.create_index(
            [('officer_id', ASCENDING), ('application_id', ASCENDING),
             ('request_id', ASCENDING)],
            name='officer_ai_feedback_request',
            unique=True,
        )
        collection.create_index(
            [('application_id', ASCENDING), ('timestamp', ASCENDING)],
            name='officer_ai_feedback_application',
        )
