"""
=============================================================================
TOOL SAFETY TESTS - Tests for rate limiting, validation, and tool execution
=============================================================================
"""
import pytest
import json
from unittest.mock import patch, MagicMock

from ai_assistant.services.tool_safety import (
    ToolRateLimiter,
    RateLimitConfig,
    ToolParameterValidator,
    ToolCallAuditor,
    safe_execute_tool,
    rate_limiter,
    get_tool_cost,
    is_expensive_tool,
)
from ai_assistant.services.tools import (
    TOOL_SCHEMAS,
    execute_tool,
    invalidate_user_tool_cache,
    _get_user_cache_key,
)


# =============================================================================
# MOCK CACHE FOR TESTING
# =============================================================================

class MockCache:
    """Simple in-memory cache for testing."""
    def __init__(self):
        self._store = {}
    
    def get(self, key, default=None):
        return self._store.get(key, default)
    
    def set(self, key, value, timeout=None):
        self._store[key] = value
    
    def delete(self, key):
        self._store.pop(key, None)
    
    def clear(self):
        self._store = {}


@pytest.fixture(autouse=True)
def mock_cache():
    """Mock Django cache for all tests."""
    mock = MockCache()
    with patch('ai_assistant.services.tool_safety.cache', mock):
        with patch('ai_assistant.services.tools.cache', mock):
            yield mock


# =============================================================================
# RATE LIMITER TESTS
# =============================================================================

class TestRateLimiter:
    """Tests for the rate limiting functionality."""
    
    def test_rate_limiter_allows_first_call(self, mock_cache):
        """First call should always be allowed."""
        limiter = ToolRateLimiter()
        result = limiter.check_rate_limit('customer_123', 'get_profile_status')
        assert result['allowed'] is True
    
    def test_rate_limiter_records_call(self, mock_cache):
        """Calls should be recorded for rate limiting."""
        limiter = ToolRateLimiter()
        customer_id = 'customer_record_test'
        
        # Record a call
        limiter.record_call(customer_id, 'get_profile_status')
        
        # Check usage stats
        stats = limiter.get_usage_stats(customer_id)
        assert stats['minute']['used'] >= 1
    
    def test_rate_limiter_blocks_after_limit(self, mock_cache):
        """Should block calls after limit is reached."""
        config = RateLimitConfig(max_calls_per_minute=3)
        limiter = ToolRateLimiter(config)
        customer_id = 'customer_limit_test'
        
        # Record max calls
        for _ in range(3):
            limiter.record_call(customer_id, 'get_profile_status')
        
        # Next call should be blocked
        result = limiter.check_rate_limit(customer_id, 'get_profile_status')
        assert result['allowed'] is False
        assert 'rate_limit_minute' in result['reason']
        assert 'retry_after_seconds' in result
    
    def test_expensive_tool_costs_more(self, mock_cache):
        """Expensive tools should consume more of the rate limit."""
        config = RateLimitConfig(
            max_calls_per_minute=5,
            tool_costs={'get_application_readiness': 3}
        )
        limiter = ToolRateLimiter(config)
        customer_id = 'customer_expensive_test'
        
        # One expensive call costs 3
        limiter.record_call(customer_id, 'get_application_readiness')
        
        # Next expensive call should be blocked (3 + 3 = 6 > 5)
        result = limiter.check_rate_limit(customer_id, 'get_application_readiness')
        assert result['allowed'] is False
    
    def test_usage_stats(self, mock_cache):
        """Should return accurate usage statistics."""
        limiter = ToolRateLimiter()
        customer_id = 'customer_stats_test'
        
        # Record some calls
        for _ in range(5):
            limiter.record_call(customer_id, 'get_profile_status')
        
        stats = limiter.get_usage_stats(customer_id)
        assert stats['minute']['used'] == 5
        assert stats['hour']['used'] == 5
        assert stats['minute']['limit'] == 30  # default
        assert stats['hour']['limit'] == 200  # default


# =============================================================================
# PARAMETER VALIDATOR TESTS
# =============================================================================

class TestParameterValidator:
    """Tests for tool parameter validation."""
    
    def test_validate_empty_params(self):
        """Tools with no parameters should pass validation."""
        result = ToolParameterValidator.validate('get_profile_status', {})
        assert result == {}
    
    def test_validate_payment_history_limit(self):
        """Payment history limit should be validated and bounded."""
        # Valid limit
        result = ToolParameterValidator.validate('get_payment_history', {'limit': 10})
        assert result['limit'] == 10
        
        # Too high - should be capped at max
        result = ToolParameterValidator.validate('get_payment_history', {'limit': 100})
        assert result['limit'] == 20  # max is 20
        
        # Too low - should be raised to min
        result = ToolParameterValidator.validate('get_payment_history', {'limit': 0})
        assert result['limit'] == 1  # min is 1
    
    def test_validate_type_coercion(self):
        """Should coerce types when possible."""
        result = ToolParameterValidator.validate('get_payment_history', {'limit': '5'})
        assert result['limit'] == 5
        assert isinstance(result['limit'], int)
    
    def test_validate_default_value(self):
        """Should use default value when not provided."""
        result = ToolParameterValidator.validate('get_payment_history', {})
        # Default is 5 for limit - should be included when not provided
        assert result == {'limit': 5}


# =============================================================================
# TOOL COST TESTS
# =============================================================================

class TestToolCosts:
    """Tests for tool cost configuration."""
    
    def test_get_tool_cost_known_tool(self):
        """Should return correct cost for known tools."""
        assert get_tool_cost('get_profile_status') == 1
        assert get_tool_cost('get_application_readiness') == 3
    
    def test_get_tool_cost_unknown_tool(self):
        """Should return 1 for unknown tools."""
        assert get_tool_cost('unknown_tool') == 1
    
    def test_is_expensive_tool(self):
        """Should correctly identify expensive tools."""
        assert is_expensive_tool('get_application_readiness') is True
        assert is_expensive_tool('get_repayment_schedule') is True
        assert is_expensive_tool('get_profile_status') is False


# =============================================================================
# SAFE EXECUTOR TESTS
# =============================================================================

class TestSafeExecutor:
    """Tests for the safe tool executor."""
    
    @patch('profiles.models.profile_models.CustomerProfile')
    @patch('profiles.models.profile_models.BusinessProfile')
    def test_safe_execute_success(self, mock_business, mock_profile, mock_cache):
        """Should execute tool and return success."""
        mock_profile.find_by_customer.return_value = None
        mock_business.find_by_customer.return_value = None
        
        result = safe_execute_tool('get_profile_status', {}, 'customer_123', skip_rate_limit=True)
        
        assert result['success'] is True
        assert result['rate_limited'] is False
        assert 'result' in result
        assert 'duration_ms' in result
    
    def test_safe_execute_rate_limited(self, mock_cache):
        """Should return rate limit error when limit exceeded."""
        # Record many calls to trigger limit
        for _ in range(35):
            rate_limiter.record_call('rate_test_customer', 'get_profile_status')
        
        result = safe_execute_tool('get_profile_status', {}, 'rate_test_customer')
        assert result['success'] is False
        assert result['rate_limited'] is True
        assert 'retry_after_seconds' in result
    
    @patch('loans.models.payment.LoanPayment')
    def test_safe_execute_validates_params(self, mock_payment, mock_cache):
        """Should validate and sanitize parameters."""
        mock_payment.find_by_customer.return_value = []
        
        # Execute with invalid params (should fail validation)
        result = safe_execute_tool(
            'get_payment_history', 
            {'limit': 'invalid'}, 
            'customer_123',
            skip_rate_limit=True
        )
        
        # Should fail validation gracefully
        assert result['success'] is False
        assert 'Invalid' in result['error']


# =============================================================================
# TOOL SCHEMA TESTS
# =============================================================================

class TestToolSchemas:
    """Tests for tool schema definitions."""
    
    def test_all_tools_have_schemas(self):
        """All tools should have proper schema definitions."""
        expected_tools = [
            'get_profile_status',
            'get_document_status',
            'get_loan_status',
            'get_repayment_schedule',
            'get_next_payment_due',
            'get_payment_history',
            'get_loan_products',
            'get_application_readiness',
        ]
        
        tool_names = [t['function']['name'] for t in TOOL_SCHEMAS]
        
        for tool in expected_tools:
            assert tool in tool_names, f"Missing schema for {tool}"
    
    def test_schemas_have_descriptions(self):
        """All tool schemas should have descriptions."""
        for schema in TOOL_SCHEMAS:
            func = schema['function']
            assert 'description' in func, f"Missing description for {func['name']}"
            assert len(func['description']) > 20, f"Description too short for {func['name']}"
    
    def test_schemas_have_parameters(self):
        """All tool schemas should have parameters object."""
        for schema in TOOL_SCHEMAS:
            func = schema['function']
            assert 'parameters' in func, f"Missing parameters for {func['name']}"
            assert func['parameters']['type'] == 'object'


# =============================================================================
# CACHE INVALIDATION TESTS
# =============================================================================

class TestCacheInvalidation:
    """Tests for tool result cache invalidation."""
    
    def test_user_cache_key_format(self, mock_cache):
        """Cache keys should be properly formatted."""
        key = _get_user_cache_key('customer_123', 'profile_status')
        assert 'ai_tool:' in key
        assert 'customer_123' in key
        assert 'profile_status' in key
    
    def test_invalidate_specific_tools(self, mock_cache):
        """Should invalidate only specified tools."""
        customer_id = 'cache_test_customer'
        
        # Set some cache values
        mock_cache.set(_get_user_cache_key(customer_id, 'profile_status'), {'test': 1}, 60)
        mock_cache.set(_get_user_cache_key(customer_id, 'document_status'), {'test': 2}, 60)
        mock_cache.set(_get_user_cache_key(customer_id, 'loan_status'), {'test': 3}, 60)
        
        # Invalidate only profile_status
        invalidate_user_tool_cache(customer_id, ['profile_status'])
        
        # profile_status should be gone, others should remain
        assert mock_cache.get(_get_user_cache_key(customer_id, 'profile_status')) is None
        assert mock_cache.get(_get_user_cache_key(customer_id, 'document_status')) == {'test': 2}
        assert mock_cache.get(_get_user_cache_key(customer_id, 'loan_status')) == {'test': 3}
    
    def test_invalidate_all_tools(self, mock_cache):
        """Should invalidate all user tool caches when no specific tools given."""
        customer_id = 'cache_all_test_customer'
        
        # Set some cache values
        mock_cache.set(_get_user_cache_key(customer_id, 'profile_status'), {'test': 1}, 60)
        mock_cache.set(_get_user_cache_key(customer_id, 'document_status'), {'test': 2}, 60)
        
        # Invalidate all
        invalidate_user_tool_cache(customer_id)
        
        # All should be gone
        assert mock_cache.get(_get_user_cache_key(customer_id, 'profile_status')) is None
        assert mock_cache.get(_get_user_cache_key(customer_id, 'document_status')) is None


# =============================================================================
# TOOL EXECUTOR TESTS
# =============================================================================

class TestToolExecutor:
    """Tests for the execute_tool function."""
    
    def test_execute_unknown_tool(self, mock_cache):
        """Should return error for unknown tools."""
        result = execute_tool('unknown_tool', {}, 'customer_123')
        result_dict = json.loads(result)
        assert 'error' in result_dict
        assert 'unknown' in result_dict['error'].lower()
    
    @patch('profiles.models.profile_models.CustomerProfile')
    @patch('profiles.models.profile_models.BusinessProfile')
    def test_execute_profile_status(self, mock_business, mock_profile, mock_cache):
        """Should execute profile status tool."""
        mock_profile.find_by_customer.return_value = None
        mock_business.find_by_customer.return_value = None
        
        result = execute_tool('get_profile_status', {}, 'customer_123')
        result_dict = json.loads(result)
        
        assert 'profile' in result_dict
        assert 'business' in result_dict
    
    @patch('loans.models.product.LoanProduct')
    def test_execute_loan_products_cached(self, mock_product, mock_cache):
        """Loan products should be cached."""
        mock_product.find.return_value = []
        
        # First call
        result1 = execute_tool('get_loan_products', {}, 'customer_123')
        
        # Second call should use cache (mock won't be called again)
        mock_product.find.reset_mock()
        result2 = execute_tool('get_loan_products', {}, 'customer_456')
        
        # Both should return same result
        assert result1 == result2
        # Second call shouldn't hit the database
        mock_product.find.assert_not_called()


# =============================================================================
# AUDITOR TESTS
# =============================================================================

class TestAuditor:
    """Tests for the tool call auditor."""
    
    def test_log_successful_call(self):
        """Should log successful calls without error."""
        # This should not raise
        ToolCallAuditor.log_call(
            customer_id='customer_123',
            tool_name='get_profile_status',
            params={},
            success=True,
            duration_ms=50
        )
    
    def test_log_failed_call(self):
        """Should log failed calls with error message."""
        # This should not raise
        ToolCallAuditor.log_call(
            customer_id='customer_123',
            tool_name='get_profile_status',
            params={},
            success=False,
            duration_ms=50,
            error='Database connection failed'
        )
    
    def test_get_recent_calls_returns_empty(self):
        """Recent calls should return empty list (placeholder implementation)."""
        result = ToolCallAuditor.get_recent_calls('customer_123')
        assert result == []
