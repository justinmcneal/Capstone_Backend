"""
=============================================================================
TOOL SAFETY - Rate limiting and validation for AI tool calls
=============================================================================

Implements safety policies to prevent abuse of tool calls:
- Per-user atomic fixed-window rate limiting
- Tool parameter validation with Pydantic
- Tool call auditing and logging
- Graceful degradation when limits reached
=============================================================================
"""
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from django.conf import settings
from django.core.cache import cache
from pymongo.errors import PyMongoError

from ai_assistant.metrics import (
    AI_AUDIT_WRITE_FAILURES,
    AI_TOOL_BUDGET_REJECTIONS,
    AI_TOOL_CALLS,
    AI_TOOL_LATENCY,
    increment,
    observe,
)
from ai_assistant.models import AIActivityEvent
from ai_assistant.services.exception_types import NON_FATAL_EXCEPTIONS

logger = logging.getLogger('ai_assistant')


# =============================================================================
# RATE LIMIT CONFIGURATION
# =============================================================================

@dataclass
class RateLimitConfig:
    """Rate limiting configuration for tool calls."""
    # Calls per window
    max_calls_per_minute: int = getattr(
        settings,
        'AI_ASSISTANT_TOOL_COST_PER_MINUTE',
        30,
    )
    max_calls_per_hour: int = getattr(
        settings,
        'AI_ASSISTANT_TOOL_COST_PER_HOUR',
        200,
    )
    # Per-tool limits (some tools more expensive than others)
    tool_costs: dict[str, int] = field(default_factory=lambda: {
        # Cost multiplier (1 = normal, 2 = counts as 2 calls, etc.)
        'get_profile_status': 1,
        'get_document_status': 1,
        'get_loan_status': 1,
        'get_repayment_schedule': 2,  # More DB queries
        'get_next_payment_due': 1,
        'get_payment_history': 2,  # Can be large
        'get_loan_products': 1,  # Cached
        'get_application_readiness': 3,  # Multiple DB queries
        'get_customer_dashboard': 3,  # Multiple aggregate/count queries
        'get_notification_status': 1,  # Single DB query
    })
    
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
    
    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RATE_LIMIT_CONFIG
    
    def _get_cache_key(
        self,
        customer_id: str,
        window: str,
        window_seconds: int,
    ) -> str:
        """Generate a fixed-window cache key without storing raw tool data."""
        bucket = int(time.time()) // window_seconds
        subject = hmac.new(
            str(settings.SECRET_KEY).encode('utf-8'),
            str(customer_id).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()[:32]
        return f"tool_ratelimit:{subject}:{window}:{bucket}"
    
    def _get_current_count(self, customer_id: str, window: str, window_seconds: int) -> int:
        """Get current call count for a window."""
        key = self._get_cache_key(customer_id, window, window_seconds)
        return int(cache.get(key, 0) or 0)
    
    def _reserve_window(
        self,
        customer_id: str,
        window: str,
        window_seconds: int,
        limit: int,
        cost: int,
    ) -> bool:
        """Atomically reserve cost in one cache-backed fixed window."""
        key = self._get_cache_key(customer_id, window, window_seconds)
        cache.add(key, 0, timeout=window_seconds + 1)
        updated = int(cache.incr(key, cost))
        if updated <= limit:
            return True
        cache.decr(key, cost)
        return False

    def _release_window(self, customer_id, window, window_seconds, cost):
        key = self._get_cache_key(customer_id, window, window_seconds)
        try:
            cache.decr(key, cost)
        except ValueError:
            logger.warning("AI tool budget rollback missed an expired cache key")
    
    def check_rate_limit(self, customer_id: str, tool_name: str) -> dict[str, Any]:
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

    def reserve_call(self, customer_id: str, tool_name: str) -> dict[str, Any]:
        """Atomically charge an attempted tool call before validation/execution."""
        tool_cost = self.config.tool_costs.get(tool_name, 1)
        if not self._reserve_window(
            customer_id,
            'minute',
            60,
            self.config.max_calls_per_minute,
            tool_cost,
        ):
            increment(AI_TOOL_BUDGET_REJECTIONS, window='minute')
            return {
                'allowed': False,
                'reason': 'rate_limit_minute',
                'retry_after_seconds': 60 - (int(time.time()) % 60),
                'message': "You're asking too many questions too quickly. Please wait a moment.",
            }
        if not self._reserve_window(
            customer_id,
            'hour',
            3600,
            self.config.max_calls_per_hour,
            tool_cost,
        ):
            self._release_window(customer_id, 'minute', 60, tool_cost)
            increment(AI_TOOL_BUDGET_REJECTIONS, window='hour')
            return {
                'allowed': False,
                'reason': 'rate_limit_hour',
                'retry_after_seconds': 3600 - (int(time.time()) % 3600),
                'message': "You've reached the hourly limit for data queries. Please try again later.",
            }
        return {'allowed': True, 'cost': tool_cost}
    
    def record_call(self, customer_id: str, tool_name: str):
        """Backward-compatible reservation helper used by diagnostics/tests."""
        return self.reserve_call(customer_id, tool_name)
    
    def get_usage_stats(self, customer_id: str) -> dict[str, Any]:
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
    SCHEMAS: ClassVar[dict[str, dict[str, Any]]] = {
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
        'get_customer_dashboard': {},
        'get_notification_status': {},
    }
    
    @classmethod
    def validate(cls, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
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
        params: dict[str, Any],
        success: bool,
        duration_ms: int,
        error: str | None = None,
        request_id: str | None = None,
        outcome: str | None = None,
        cost: int = 1,
    ):
        """Persist and log metadata only; params/error content are never stored."""
        outcome = outcome or ('success' if success else 'execution_error')
        safe_tool_name = (
            tool_name if tool_name in RATE_LIMIT_CONFIG.tool_costs else 'unknown'
        )
        try:
            AIActivityEvent.record_tool_call(
                customer_id=customer_id,
                tool_name=safe_tool_name,
                success=success,
                outcome=outcome,
                duration_ms=duration_ms,
                cost=cost,
                request_id=request_id,
            )
        except (PyMongoError, AttributeError, RuntimeError, TypeError, ValueError):
            increment(AI_AUDIT_WRITE_FAILURES)
            logger.error(
                "AI tool audit persistence failed",
                extra={
                    'request_id': request_id,
                    'tool': safe_tool_name,
                    'outcome': outcome,
                },
            )
        log_method = logger.info if success else logger.warning
        log_method(
            "AI tool call completed",
            extra={
                'request_id': request_id,
                'tool': safe_tool_name,
                'outcome': outcome,
                'duration_ms': duration_ms,
                'cost': cost,
            },
        )
    
    @staticmethod
    def get_recent_calls(customer_id: str, limit: int = 10) -> list[dict]:
        """Return bounded metadata-only audit entries for internal diagnostics."""
        return AIActivityEvent.recent_for_customer(customer_id, limit=limit)


auditor = ToolCallAuditor()


# =============================================================================
# SAFE TOOL EXECUTOR
# =============================================================================

def safe_execute_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    customer_id: str,
    skip_rate_limit: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
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
    import json
    import time

    from ai_assistant.services.tools import _execute_tool_raw
    
    start_time = time.time()
    
    # 1. Check rate limit
    tool_cost = get_tool_cost(tool_name)
    metric_tool = tool_name if tool_name in RATE_LIMIT_CONFIG.tool_costs else 'unknown'
    if not skip_rate_limit:
        limit_check = rate_limiter.reserve_call(customer_id, tool_name)
        if not limit_check['allowed']:
            outcome = f"rate_limited_{limit_check['reason'].removeprefix('rate_limit_')}"
            auditor.log_call(
                customer_id, tool_name, tool_args,
                success=False, duration_ms=0,
                error=f"Rate limited: {limit_check['reason']}",
                request_id=request_id,
                outcome=outcome,
                cost=tool_cost,
            )
            increment(AI_TOOL_CALLS, tool=metric_tool, outcome=outcome)
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
            error=f"Validation error: {e!s}",
            request_id=request_id,
            outcome='validation_error',
            cost=tool_cost,
        )
        increment(AI_TOOL_CALLS, tool=metric_tool, outcome='validation_error')
        observe(AI_TOOL_LATENCY, duration_ms / 1000, tool=metric_tool)
        return {
            'success': False,
            'error': f"Invalid parameters: {e!s}",
            'rate_limited': False
        }
    
    # 3. Execute tool
    try:
        result_data = _execute_tool_raw(tool_name, validated_args, customer_id)
        result = json.dumps(result_data, default=str)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 4. Audit metadata. Budget was reserved before validation/execution.
        auditor.log_call(
            customer_id, tool_name, validated_args,
            success=True, duration_ms=duration_ms,
            request_id=request_id,
            outcome='success',
            cost=tool_cost,
        )
        increment(AI_TOOL_CALLS, tool=metric_tool, outcome='success')
        observe(AI_TOOL_LATENCY, duration_ms / 1000, tool=metric_tool)
        
        return {
            'success': True,
            'result': result,
            'rate_limited': False,
            'duration_ms': duration_ms
        }
        
    except NON_FATAL_EXCEPTIONS as e:
        duration_ms = int((time.time() - start_time) * 1000)
        auditor.log_call(
            customer_id, tool_name, tool_args,
            success=False, duration_ms=duration_ms,
            error=str(e),
            request_id=request_id,
            outcome='execution_error',
            cost=tool_cost,
        )
        increment(AI_TOOL_CALLS, tool=metric_tool, outcome='execution_error')
        observe(AI_TOOL_LATENCY, duration_ms / 1000, tool=metric_tool)
        logger.error(
            "AI tool execution failed",
            extra={'request_id': request_id, 'tool': tool_name},
        )
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


def get_all_tool_costs() -> dict[str, int]:
    """Get all tool costs for documentation/debugging."""
    return dict(RATE_LIMIT_CONFIG.tool_costs)
