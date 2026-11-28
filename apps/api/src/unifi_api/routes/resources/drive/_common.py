"""Drive route plumbing: the console product helpers bound to Drive.

The path ``site_id`` is the controller site of the other console products and
is ignored here: a UniFi Drive NAS has no sites.
"""

from __future__ import annotations

from unifi_api.routes.resources._console_product import ConsoleResources
from unifi_api.services.drive import DRIVE, ID_FAMILY

SITE_NOTE = f"The path site_id is ignored. Read-only, through the NAS console session. {ID_FAMILY}"

_resources = ConsoleResources(DRIVE)
read = _resources.read
detail = _resources.detail
items = _resources.items
