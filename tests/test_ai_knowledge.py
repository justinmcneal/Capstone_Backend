"""
Tests for AI Knowledge Base and System Prompt
==============================================

These tests ensure the AI knowledge base maintains consistency and
catches regressions when updating platform information.
"""
import pytest
from ai_assistant.services.knowledge_base import (
    KNOWLEDGE_VERSION,
    KNOWLEDGE_BASE,
    PLATFORM_INFO,
    LOAN_PRODUCTS_INFO,
    PAYMENT_METHODS,
    PROHIBITED_TOPICS,
    REDIRECT_RESPONSES,
    build_system_prompt,
    check_prohibited_content,
)


class TestKnowledgeBaseStructure:
    """Test that the knowledge base has all required sections."""
    
    def test_knowledge_version_exists(self):
        """Knowledge base should have a version."""
        assert KNOWLEDGE_VERSION is not None
        assert len(KNOWLEDGE_VERSION) > 0
    
    def test_platform_info_complete(self):
        """Platform info should have required fields."""
        required_fields = ['name', 'type', 'target_users', 'blockchain']
        for field in required_fields:
            assert field in PLATFORM_INFO, f"Missing platform field: {field}"
    
    def test_loan_products_info_complete(self):
        """Loan products info should have amount and term ranges."""
        assert 'amount_range' in LOAN_PRODUCTS_INFO
        assert 'min' in LOAN_PRODUCTS_INFO['amount_range']
        assert 'max' in LOAN_PRODUCTS_INFO['amount_range']
        assert 'term_range' in LOAN_PRODUCTS_INFO
        assert 'interest' in LOAN_PRODUCTS_INFO
    
    def test_payment_methods_complete(self):
        """Payment methods should have automatic and manual categories."""
        assert 'automatic' in PAYMENT_METHODS
        assert 'manual' in PAYMENT_METHODS
        assert len(PAYMENT_METHODS['automatic']['methods']) >= 3
        assert len(PAYMENT_METHODS['manual']['methods']) >= 2
    
    def test_knowledge_base_dict_complete(self):
        """KNOWLEDGE_BASE dict should have all sections."""
        required_keys = [
            'version', 'platform', 'loan_products', 'loan_process',
            'payment_methods', 'document_types', 'application_statuses',
        ]
        for key in required_keys:
            assert key in KNOWLEDGE_BASE, f"Missing knowledge base key: {key}"


class TestSystemPrompt:
    """Test system prompt generation."""
    
    def test_system_prompt_builds(self):
        """System prompt should build without errors."""
        prompt = build_system_prompt()
        assert prompt is not None
        assert len(prompt) > 500  # Should be substantial
    
    def test_system_prompt_contains_platform_name(self):
        """System prompt should mention MSME Pathways."""
        prompt = build_system_prompt()
        assert 'MSME Pathways' in prompt
    
    def test_system_prompt_contains_payment_methods(self):
        """System prompt should list payment methods."""
        prompt = build_system_prompt()
        assert 'GCash' in prompt
        assert 'Bank Transfer' in prompt
        assert 'Cash' in prompt
    
    def test_system_prompt_contains_loan_amounts(self):
        """System prompt should include loan amount range."""
        prompt = build_system_prompt()
        assert '5,000' in prompt or '₱5,000' in prompt
        assert '50,000' in prompt or '₱50,000' in prompt
    
    def test_system_prompt_contains_guidelines(self):
        """System prompt should include AI behavior guidelines."""
        prompt = build_system_prompt()
        assert 'Never' in prompt or 'never' in prompt
        assert 'password' in prompt.lower() or 'PIN' in prompt
    
    def test_system_prompt_with_version(self):
        """System prompt should optionally include version."""
        prompt_with_version = build_system_prompt(include_version=True)
        assert f'v{KNOWLEDGE_VERSION}' in prompt_with_version
        
        prompt_without = build_system_prompt(include_version=False)
        assert f'v{KNOWLEDGE_VERSION}' not in prompt_without


class TestContentFilter:
    """Test prohibited content detection."""
    
    def test_normal_message_not_filtered(self):
        """Normal loan questions should not be filtered."""
        messages = [
            "How do I apply for a loan?",
            "What documents do I need?",
            "What is my loan status?",
            "How much can I borrow?",
        ]
        for msg in messages:
            is_prohibited, _ = check_prohibited_content(msg)
            assert not is_prohibited, f"Normal message incorrectly filtered: {msg}"

    def test_account_help_message_not_filtered(self):
        """Account-support questions should not be mistaken for credential sharing."""
        messages = [
            "How do I reset my password?",
            "Can you explain the forgot-password OTP flow?",
            "Where do I verify my email OTP?",
            "How do I set up 2FA?",
            "How can I change my password safely?",
        ]
        for msg in messages:
            is_prohibited, _ = check_prohibited_content(msg)
            assert not is_prohibited, f"Account-help message incorrectly filtered: {msg}"
    
    def test_credential_request_filtered(self):
        """Requests for credentials should be filtered."""
        messages = [
            "What is your password?",
            "What is my password?",
            "Give me your PIN",
            "Tell me your OTP",
            "What's the private key?",
            "Here is my OTP: 123456",
        ]
        for msg in messages:
            is_prohibited, response = check_prohibited_content(msg)
            assert is_prohibited, f"Credential request not filtered: {msg}"
            assert response is not None
            assert 'never' in response.lower() or 'scam' in response.lower()
    
    def test_guarantee_request_filtered(self):
        """Requests for approval guarantees should be filtered."""
        messages = [
            "Will I be approved for sure?",
            "Can you guarantee approval?",
        ]
        for msg in messages:
            is_prohibited, response = check_prohibited_content(msg)
            assert is_prohibited, f"Guarantee request not filtered: {msg}"
            assert response is not None
    
    def test_legal_request_filtered(self):
        """Requests for legal advice should be filtered."""
        messages = [
            "Should I sue them?",
            "I need a lawyer",
            "Can I take legal action?",
        ]
        for msg in messages:
            is_prohibited, response = check_prohibited_content(msg)
            assert is_prohibited, f"Legal request not filtered: {msg}"
            assert 'legal' in response.lower() or 'lawyer' in response.lower()


class TestLoanProductConsistency:
    """Test that loan product info is consistent."""
    
    def test_min_amount_less_than_max(self):
        """Min loan amount should be less than max."""
        min_amt = LOAN_PRODUCTS_INFO['amount_range']['min']
        max_amt = LOAN_PRODUCTS_INFO['amount_range']['max']
        assert min_amt < max_amt
    
    def test_min_term_less_than_max(self):
        """Min term should be less than max."""
        min_term = LOAN_PRODUCTS_INFO['term_range']['min_months']
        max_term = LOAN_PRODUCTS_INFO['term_range']['max_months']
        assert min_term < max_term
    
    def test_interest_rate_reasonable(self):
        """Interest rate should be reasonable (0.5% - 5% monthly)."""
        rate = LOAN_PRODUCTS_INFO['interest']['default_monthly_rate']
        assert 0.5 <= rate <= 5.0


class TestRedirectResponses:
    """Test that redirect responses exist for all prohibited topics."""
    
    def test_all_redirect_responses_exist(self):
        """All redirect response keys should have non-empty values."""
        for key, value in REDIRECT_RESPONSES.items():
            assert value is not None, f"Missing redirect response for: {key}"
            assert len(value) > 20, f"Redirect response too short for: {key}"
    
    def test_redirect_responses_are_helpful(self):
        """Redirect responses should provide guidance."""
        # Credentials response should warn about scams
        assert 'scam' in REDIRECT_RESPONSES['credentials'].lower() or \
               'never' in REDIRECT_RESPONSES['credentials'].lower()
        
        # Guarantee response should explain decisions depend on review
        assert 'decision' in REDIRECT_RESPONSES['guarantee'].lower() or \
               'guarantee' in REDIRECT_RESPONSES['guarantee'].lower()
