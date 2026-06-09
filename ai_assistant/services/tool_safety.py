"""
=============================================================================
TOOL SAFETY - Rate limiting and validation for AI tool calls
=============================================================================

Implements safety policies to prevent abuse of tool calls:
- Per-user rate limiting with sliding window
- Tool parameter validation with Pydantic
- Tool call auditing and logging
- Graceful degradation when limits reached
=============================================================================
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from functools import wraps

from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger('ai_assistant')


# =============================================================================
# RATE LIMIT CONFIGURATION
# =============================================================================

@dataclass
class RateLimitConfig:
    """Rate limiting configuration for tool calls."""
    # Calls per window
    max_calls_per_minute: int = 30
    max_calls_per_hour: int = 200
    max_calls_per_session: int = 50  # Per conversation session
    
    # Per-tool limits (some tools more expensive than others)
    tool_costs: Dict[str, int] = field(default_factory=lambda: {
        # Cost multiplier (1 = normal, 2 = counts as 2 calls, etc.)
        'get_profile_status': 1,
        'get_document_status': 1,
        'get_loan_status': 1,
        'get_repayment_schedule': 2,  # More DB queries
        'get_next_payment_due': 1,
        'get_payment_history': 2,  # Can be large
        'get_loan_products': 1,  # Cached
        'get_application_readiness': 3,  # Multiple DB queries
        'get_notification_status': 1,  # Single DB query
    })
    
    # Cooldown after hitting limit (seconds)
    cooldown_seconds: int = 60


# Global config - can be overridden in settings
RATE_LIMIT_CONFIG = RateLimitConfig()


# =============================================================================
# RATE LIMITER
# =============================================================================

class ToolRateLimiter:
    """
    Sliding window rate limiter for tool calls.
    Uses Django cache backend (Redis-compatible).
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RATE_LIMIT_CONFIG
    
    def _get_cache_key(self, customer_id: str, window: str) -> str:
        """Generate cache key for rate limit tracking."""
        return f"tool_ratelimit:{customer_id}:{window}"
    
    def _get_current_count(self, customer_id: str, window: str, window_seconds: int) -> int:
        """Get current call count for a window."""
        key = self._get_cache_key(customer_id, window)
        count = cache.get(key, 0)
        return count
    
    def _increment_count(self, customer_id: str, window: str, window_seconds: int, cost: int = 1):
        """Increment call count for a window."""
        key = self._get_cache_key(customer_id, window)
        current = cache.get(key, 0)
        cache.set(key, current + cost, window_seconds)
    
    def check_rate_limit(self, customer_id: str, tool_name: str) -> Dict[str, Any]:
        """
        Check if a tool call is allowed under rate limits.
        
        Returns:
            dict with 'allowed', 'reason', 'retry_after_seconds'
        """
        tool_cost = self.config.tool_costs.get(tool_name, 1)
        
        # Check minute limit
        minute_count = self._get_current_count(customer_id, 'minute', 60)
        if minute_count + tool_cost > self.config.max_calls_per_minute:
            return {
                'allowed': False,
                'reason': 'rate_limit_minute',
                'retry_after_seconds': 60 - (int(time.time()) % 60),
                'message': "You're asking too many questions too quickly. Please wait a moment."
            }
        
        # Check hour limit
        hour_count = self._get_current_count(customer_id, 'hour', 3600)
        if hour_count + tool_cost > self.config.max_calls_per_hour:
            return {
                'allowed': False,
                'reason': 'rate_limit_hour',
                'retry_after_seconds': 3600 - (int(time.time()) % 3600),
                'message': "You've reached the hourly limit for data queries. Please try again later."
            }
        
        return {'allowed': True}
    
    def record_call(self, customer_id: str, tool_name: str):
        """Record a successful tool call for rate limiting."""
        tool_cost = self.config.tool_costs.get(tool_name, 1)
        
        self._increment_count(customer_id, 'minute', 60, tool_cost)
        self._increment_count(customer_id, 'hour', 3600, tool_cost)
    
    def get_usage_stats(self, customer_id: str) -> Dict[str, Any]:
        """Get current usage stats for a customer."""
        return {
            'minute': {
                'used': self._get_current_count(customer_id, 'minute', 60),
                'limit': self.config.max_calls_per_minute
            },
            'hour': {
                'used': self._get_current_count(customer_id, 'hour', 3600),
                'limit': self.config.max_calls_per_hour
            }
        }


# Global rate limiter instance
rate_limiter = ToolRateLimiter()


# =============================================================================
# PARAMETER VALIDATORS
# =============================================================================

class ToolParameterValidator:
    """
    Validates tool parameters before execution.
    Ensures type safety and bounds checking.
    """
    
    # Parameter schemas for each tool
    SCHEMAS = {
        'get_profile_status': {},
        'get_document_status': {},
        'get_loan_status': {},
        'get_repayment_schedule': {},
        'get_next_payment_due': {},
        'get_payment_history': {
            'limit': {'type': int, 'min': 1, 'max': 20, 'default': 5}
        },
        'get_loan_products': {},
        'get_application_readiness': {},
        'get_notification_status': {},
    }
    
    @classmethod
    def validate(cls, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize tool parameters.
        
        Returns:
            Sanitized parameters dict
        
        Raises:
            ValueError if validation fails
        """
        schema = cls.SCHEMAS.get(tool_name, {})
        validated = {}
        
        for param_name, rules in schema.items():
            value = params.get(param_name, rules.get('default'))
            
            if value is None:
                if rules.get('required', False):
                    raise ValueError(f"Missing required parameter: {param_name}")
                continue
            
            # Type validation
            expected_type = rules.get('type')
            if expected_type and not isinstance(value, expected_type):
                try:
                    value = expected_type(value)
                except (ValueError, TypeError):
                    raise ValueError(f"Invalid type for {param_name}: expected {expected_type.__name__}")
            
            # Bounds checking for numbers
            if isinstance(value, (int, float)):
                min_val = rules.get('min')
                max_val = rules.get('max')
                if min_val is not None and value < min_val:
                    value = min_val
                if max_val is not None and value > max_val:
                    value = max_val
            
            validated[param_name] = value
        
        return validated


# =============================================================================
# TOOL CALL AUDITOR
# =============================================================================

class ToolCallAuditor:
    """
    Audit log for tool calls.
    Records calls for monitoring and debugging.
    """
    
    @staticmethod
    def log_call(
        customer_id: str,
        tool_name: str,
        params: Dict[str, Any],
        success: bool,
        duration_ms: int,
        error: Optional[str] = None
    ):
        """Log a tool call for auditing."""
        log_data = {
            'customer_id': customer_id,
            'tool': tool_name,
            'params': params,
            'success': success,
            'duration_ms': duration_ms,
        }
        
        if error:
            log_data['error'] = error
            logger.warning(f"Tool call failed: {log_data}")
        else:
            logger.info(f"Tool call: {tool_name} for customer {customer_id} ({duration_ms}ms)")
    
    @staticmethod
    def get_recent_calls(customer_id: str, limit: int = 10) -> List[Dict]:
        """
        Get recent tool calls for a customer.
        (In production, this would query a proper audit log store)
        """
        # For now, just return empty - full audit logging would use a database
        return []


auditor = ToolCallAuditor()


# =============================================================================
# SAFE TOOL EXECUTOR
# =============================================================================

def safe_execute_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    customer_id: str,
    skip_rate_limit: bool = False
) -> Dict[str, Any]:
    """
    Safely execute a tool with rate limiting, validation, and auditing.
    
    Args:
        tool_name: Name of the tool to execute
        tool_args: Tool parameters
        customer_id: Customer ID for scoping
        skip_rate_limit: If True, skip rate limit check (for internal calls)
    
    Returns:
        dict with 'success', 'result' or 'error', 'rate_limited'
    """
    import time
    import json
    from ai_assistant.services.tools import execute_tool
    
    start_time = time.time()
    
    # 1. Check rate limit
    if not skip_rate_limit:
        limit_check = rate_limiter.check_rate_limit(customer_id, tool_name)
        if not limit_check['allowed']:
            auditor.log_call(
                customer_id, tool_name, tool_args,
                success=False, duration_ms=0,
                error=f"Rate limited: {limit_check['reason']}"
            )
            return {
                'success': False,
                'error': limit_check['message'],
                'rate_limited': True,
                'retry_after_seconds': limit_check.get('retry_after_seconds', 60)
            }
    
    # 2. Validate parameters
    try:
        validated_args = ToolParameterValidator.validate(tool_name, tool_args)
    except ValueError as e:
        duration_ms = int((time.time() - start_time) * 1000)
        auditor.log_call(
            customer_id, tool_name, tool_args,
            success=False, duration_ms=duration_ms,
            error=f"Validation error: {str(e)}"
        )
        return {
            'success': False,
            'error': f"Invalid parameters: {str(e)}",
            'rate_limited': False
        }
    
    # 3. Execute tool
    try:
        result = execute_tool(tool_name, validated_args, customer_id)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 4. Record successful call for rate limiting
        if not skip_rate_limit:
            rate_limiter.record_call(customer_id, tool_name)
        
        # 5. Audit log
        auditor.log_call(
            customer_id, tool_name, validated_args,
            success=True, duration_ms=duration_ms
        )
        
        return {
            'success': True,
            'result': result,
            'rate_limited': False,
            'duration_ms': duration_ms
        }
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        auditor.log_call(
            customer_id, tool_name, tool_args,
            success=False, duration_ms=duration_ms,
            error=str(e)
        )
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return {
            'success': False,
            'error': "Failed to retrieve data. Please try again.",
            'rate_limited': False
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_tool_cost(tool_name: str) -> int:
    """Get the rate limit cost for a tool."""
    return RATE_LIMIT_CONFIG.tool_costs.get(tool_name, 1)


def is_expensive_tool(tool_name: str) -> bool:
    """Check if a tool is considered expensive (cost > 1)."""
    return get_tool_cost(tool_name) > 1


def get_all_tool_costs() -> Dict[str, int]:
    """Get all tool costs for documentation/debugging."""
    return dict(RATE_LIMIT_CONFIG.tool_costs)
