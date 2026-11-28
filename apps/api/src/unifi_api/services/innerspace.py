"""InnerSpace reads for the REST and GraphQL surfaces, and their fixed-text errors.

InnerSpace is a console product (:mod:`unifi_api.services.console_product`):
both surfaces reach the same core manager method with the same arguments
through its shared read, and map a failure the same way. The action
endpoint keeps its generic contract and audits the exception class instead.

Core InnerSpace errors are built from fixed text (see the InnerSpace session
isolation rules), so their text is returned. Invalid arguments and a missing
resource get fixed text of their own: the rejected value is never echoed.
Anything unexpected is logged by class and answered with fixed text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from unifi_core.innerspace.managers.connection_manager import InnerSpaceHttpError
from unifi_core.innerspace.models.reads import InnerSpaceListInput

from unifi_api.services.console_product import ConsoleProduct, ConsoleProductAPIError, map_error

PRODUCT = "innerspace"
DEFAULT_LIMIT: int = InnerSpaceListInput.model_fields["limit"].default
ID_FAMILY = "These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools."


class InnerSpaceAPIError(ConsoleProductAPIError):
    """A mapped InnerSpace failure: HTTP status, stable kind and fixed message."""

    product = PRODUCT


def _restarting(exc: BaseException) -> bool:
    # The InnerSpace application is restarting or busy: retryable, like a Network 503.
    return isinstance(exc, InnerSpaceHttpError) and exc.status == 503


INNERSPACE = ConsoleProduct(
    error=InnerSpaceAPIError, label="InnerSpace", log_name="InnerSpace", unavailable=_restarting
)


def map_innerspace_error(exc: BaseException, operation: str) -> BaseException:
    """Map an InnerSpace failure to a status and fixed text, as for every console product."""
    return map_error(INNERSPACE, exc, operation)


def page_with_limit(page: Any, limit: int) -> dict[str, Any]:
    """A wall or placed-device page as a dict, with the limit it was cut at."""
    data = page.model_dump() if isinstance(page, BaseModel) else dict(page)
    return {**data, "limit": limit}
