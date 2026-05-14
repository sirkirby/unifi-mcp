import pytest
from unifi_core.exceptions import UniFiConnectionError
from unifi_core.retry import RetryPolicy, retry_with_backoff


@pytest.mark.asyncio
async def test_retry_succeeds_after_failures():
    call_count = 0

    async def flaky_operation():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise UniFiConnectionError("Connection failed")
        return "success"

    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    result = await retry_with_backoff(flaky_operation, policy)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    async def always_fails():
        raise UniFiConnectionError("Connection failed")

    policy = RetryPolicy(max_retries=2, base_delay=0.01)
    with pytest.raises(UniFiConnectionError):
        await retry_with_backoff(always_fails, policy)


@pytest.mark.asyncio
async def test_retry_succeeds_on_first_try():
    async def succeeds():
        return "ok"

    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    result = await retry_with_backoff(succeeds, policy)
    assert result == "ok"


@pytest.mark.asyncio
async def test_retry_non_retryable_exception_not_caught():
    async def raises_value_error():
        raise ValueError("not retryable")

    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    with pytest.raises(ValueError, match="not retryable"):
        await retry_with_backoff(raises_value_error, policy)


def test_retry_policy_defaults():
    policy = RetryPolicy()
    assert policy.max_retries == 3
    assert policy.base_delay == 1.0
    assert policy.max_delay == 30.0
    assert policy.backoff_factor == 2.0
