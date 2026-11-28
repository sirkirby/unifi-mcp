"""InnerSpace route plumbing: the console product helpers bound to InnerSpace, and its query parameters.

The path ``site_id`` is the controller site of the other console products and
is ignored here. The InnerSpace site filter is the ``innerspace_site_id`` query
parameter.
"""

from __future__ import annotations

from fastapi import Query

from unifi_api.routes.resources._console_product import ConsoleResources
from unifi_api.services.innerspace import DEFAULT_LIMIT, ID_FAMILY, INNERSPACE

SITE_NOTE = (
    "The path site_id is ignored; filter by InnerSpace site with innerspace_site_id. Read-only, through the console "
    f"session. {ID_FAMILY}"
)

SiteQuery = Query(
    None,
    description=f"InnerSpace site id to filter by; omit for every site. {ID_FAMILY}",
)
# The bounds are stated in the schema only: the core input model validates them, so a bad value
# gets InnerSpace's fixed-text 422 rather than the generic request-validation answer.
UnitQuery = Query(
    None,
    description="Length unit of the result: 'metric' or 'imperial'. Omit to use the project's own unit.",
    json_schema_extra={"enum": ["metric", "imperial"]},
)
LimitQuery = Query(
    DEFAULT_LIMIT,
    description="Maximum entries to return, 1 to 2000. The result reports the total and whether it was cut.",
    json_schema_extra={"minimum": 1, "maximum": 2000},
)

_resources = ConsoleResources(INNERSPACE)
read = _resources.read
detail = _resources.detail
items = _resources.items
