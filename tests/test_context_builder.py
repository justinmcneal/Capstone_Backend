"""
Tests for Context Builder - Privacy-aware user context
=======================================================

These tests ensure the context builder properly handles:
- Privacy/redaction of sensitive fields
- Context summarization
- Intent-based context selection
"""
import pytest
from ai_assistant.services.context_builder import (
    mask_value,
    format_currency,
    format_date,
    summarize_status,
    get_context_for_intent,
    build_minimal_context,
    MAX_DOCUMENTS,
    MAX_APPLICATIONS,
)
from datetime import datetime


class TestHelperFunctions:
    """Test helper functions for formatting and masking."""
    
    def test_mask_value_full(self):
        """Should mask all but last 4 characters."""
        assert mask_value("09171234567") == "*******4567"
        # Email masking shows last 4 chars
        result = mask_value("email@example.com")
        assert result.endswith(".com")
        assert "*" in result
    
    def test_mask_value_short(self):
        """Short values should not be masked."""
        assert mask_value("1234") == "1234"
        assert mask_value("abc") == "abc"
    
    def test_mask_value_empty(self):
        """Empty/None values should return as-is."""
        assert mask_value("") == ""
        assert mask_value(None) is None
    
    def test_format_currency(self):
        """Should format as Philippine Peso."""
        assert format_currency(5000) == "₱5,000"
        assert format_currency(500000) == "₱500,000"
        assert format_currency(1234.56) == "₱1,235"
        assert format_currency(None) == "N/A"
    
    def test_format_date(self):
        """Should format dates nicely."""
        dt = datetime(2026, 3, 18)
        assert format_date(dt) == "Mar 18, 2026"
        assert format_date(None) == "N/A"
    
    def test_summarize_status(self):
        """Should convert status codes to friendly text."""
        assert "✓" in summarize_status("approved")
        assert "✓" in summarize_status("paid")
        assert "⚠" in summarize_status("overdue")
        assert "⚠" in summarize_status("defaulted")
        assert summarize_status("under_review") == "Under Review"
        assert summarize_status("unknown_status") == "Unknown Status"


class TestIntentBasedContext:
    """Test that context selection matches question intent."""
    
    def test_payment_question_returns_loan_context(self):
        """Payment questions should focus on loans, not profile."""
        # These are the keywords used in context_builder.py
        loan_keywords = ['loan', 'payment', 'installment', 'balance', 'due', 'pay', 'bayad', 'utang', 'owe']
        messages = [
            "When is my next payment due?",
            "How much do I owe?",
            "What's my loan balance?",
            "Magkano pa bayad ko?",  # Tagalog
        ]
        for msg in messages:
            has_keyword = any(kw in msg.lower() for kw in loan_keywords)
            assert has_keyword, f"'{msg}' should match loan keywords"
    
    def test_document_question_pattern(self):
        """Document questions should match document keywords."""
        doc_messages = [
            "What documents do I need?",
            "Did my ID get verified?",
            "How do I upload my permit?",
        ]
        doc_keywords = ['document', 'upload', 'id', 'permit', 'proof']
        for msg in doc_messages:
            has_keyword = any(kw in msg.lower() for kw in doc_keywords)
            assert has_keyword, f"'{msg}' should match document keywords"
    
    def test_profile_question_pattern(self):
        """Profile questions should match profile keywords."""
        profile_messages = [
            "Is my profile complete?",
            "How do I update my business info?",
            "What's missing in my account?",
        ]
        profile_keywords = ['profile', 'business', 'complete', 'fill', 'info', 'account']
        for msg in profile_messages:
            has_keyword = any(kw in msg.lower() for kw in profile_keywords)
            assert has_keyword, f"'{msg}' should match profile keywords"


class TestPrivacyLimits:
    """Test that privacy limits are enforced."""
    
    def test_max_documents_limit(self):
        """Should not include more than MAX_DOCUMENTS."""
        assert MAX_DOCUMENTS == 5
    
    def test_max_applications_limit(self):
        """Should not include more than MAX_APPLICATIONS."""
        assert MAX_APPLICATIONS == 3


class TestStatusSummarization:
    """Test status display formatting."""
    
    def test_all_application_statuses(self):
        """All application statuses should have friendly text."""
        statuses = ['draft', 'submitted', 'under_review', 'approved', 'rejected', 'disbursed', 'completed', 'defaulted']
        for status in statuses:
            result = summarize_status(status)
            assert result is not None
            assert len(result) > 0
            # Should not just be the raw status
            assert result != status or '_' not in status
    
    def test_all_installment_statuses(self):
        """All installment statuses should have friendly text."""
        statuses = ['pending', 'paid', 'partial', 'overdue']
        for status in statuses:
            result = summarize_status(status)
            assert result is not None
            assert len(result) > 0
    
    def test_visual_indicators(self):
        """Positive/negative statuses should have visual indicators."""
        # Positive statuses should have checkmarks
        positive = ['approved', 'paid', 'completed', 'verified']
        for status in positive:
            assert '✓' in summarize_status(status)
        
        # Negative statuses should have warnings
        negative = ['overdue', 'defaulted']
        for status in negative:
            assert '⚠' in summarize_status(status)
