"""The projection base and shared description of the Drive Strawberry types."""

from __future__ import annotations

from unifi_api.graphql.types._projection import ConsoleProjection
from unifi_api.services.drive import DRIVE, ID_FAMILY

DESCRIPTION = f"UniFi Drive read, through the NAS console session. {ID_FAMILY}"


class Projection(ConsoleProjection):
    _product_label = DRIVE.label
