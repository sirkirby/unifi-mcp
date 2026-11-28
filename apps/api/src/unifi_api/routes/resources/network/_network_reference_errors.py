"""Translate typed upstream failures from the network references read."""

from collections.abc import Awaitable
from typing import TypeVar

from fastapi import HTTPException
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
)

T = TypeVar("T")


async def reference_read(call: Awaitable[T]) -> T:
    try:
        return await call
    except UniFiNotFoundError:
        raise HTTPException(404, detail="No network on this controller has that id.") from None
    except UniFiPermissionError:
        raise HTTPException(403, detail="The controller account lacks permission for this read.") from None
    except UniFiAuthError:
        raise HTTPException(502, detail="The controller rejected the configured credentials.") from None
    except (UniFiConnectionError, UniFiMalformedResponseError, UniFiOperationError):
        raise HTTPException(502, detail="The controller could not complete this read.") from None
