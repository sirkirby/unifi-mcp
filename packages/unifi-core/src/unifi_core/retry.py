"""Retry logic with exponential backoff."""

import asyncio
import logging
from dataclasses import dataclass

from unifi_core.exceptions import UniFiError

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0
    retryable_exceptions: tuple = (UniFiError,)


async def retry_with_backoff(operation, policy: RetryPolicy | None = None):
    """Execute operation with exponential backoff retry."""
    if policy is None:
        policy = RetryPolicy()

    last_error = None
    for attempt in range(policy.max_retries + 1):
        try:
            return await operation()
        except policy.retryable_exceptions as e:
            last_error = e
            if attempt < policy.max_retries:
                delay = min(policy.base_delay * (policy.backoff_factor**attempt), policy.max_delay)
                logger.warning(
                    "[retry] Attempt %d/%d failed: %s. Retrying in %.1fs",
                    attempt + 1,
                    policy.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

    raise last_error
