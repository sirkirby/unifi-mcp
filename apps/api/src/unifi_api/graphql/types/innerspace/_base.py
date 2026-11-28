"""The projection base and shared description of the InnerSpace Strawberry types."""

from __future__ import annotations

from unifi_api.graphql.types._projection import ConsoleProjection
from unifi_api.services.innerspace import ID_FAMILY, INNERSPACE

DESCRIPTION = f"UniFi InnerSpace read, through the console session. {ID_FAMILY}"
IMAGE_SCALE = "The plan map's image scale, or null when not sent or when its y scale differs from x"


class Projection(ConsoleProjection):
    _product_label = INNERSPACE.label
