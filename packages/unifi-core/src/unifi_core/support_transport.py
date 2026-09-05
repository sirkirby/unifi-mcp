"""Request-local transport controls for one-shot support probes."""

import aiohttp


async def no_retry_support_request(
    request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    """Prevent aiohttp's idempotent-request retry without mutating its session.

    aiohttp retries ClientOSError and ServerDisconnectedError after a GET's
    connection fails. Per-request middleware runs inside that retry loop. Reduce
    those failures to their non-retried parent class before the loop sees them.
    No original error text is copied or logged; managers emit only fixed outcomes.
    """
    try:
        return await handler(request)
    except (aiohttp.ClientOSError, aiohttp.ServerDisconnectedError):
        raise aiohttp.ClientConnectionError("Support connectivity transport failed") from None
