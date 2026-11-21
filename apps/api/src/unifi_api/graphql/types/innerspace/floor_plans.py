"""InnerSpace floor plans and plan image metadata (never the image itself)."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.types.innerspace._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class InnerSpaceFloorPlan(Projection):
    id: str | None = strawberry.field(description="InnerSpace floor plan id")
    name: str | None = strawberry.field(description="Plan name")
    floor_number: float | None = strawberry.field(description="Floor number")
    scale_per_unit: float | None = strawberry.field(description="Plan units per metre, or per foot when imperial")
    width_px: float | None = strawberry.field(description="Plan image width in pixels")
    height_px: float | None = strawberry.field(description="Plan image height in pixels")
    origin_x: float | None = strawberry.field(description="Plan origin x as the console sent it")
    origin_y: float | None = strawberry.field(description="Plan origin y as the console sent it")
    site_id: str | None = strawberry.field(description="InnerSpace site id")
    image_filename: str | None = strawberry.field(description="Asset file name taken from the image URL")
    image_scale: float | None = strawberry.field(description="The plan map's horizontal image scale, if sent")
    image_offset: list[float] | None = strawberry.field(description="The plan map's image offset (x, y)")
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")

    _identity = "id"
    _columns = ["name", "floor_number", "scale_per_unit"]


@strawberry.type(
    description=(
        "Image metadata of one floor plan. The API never returns the image; read it through the InnerSpace MCP "
        f"server's plan image resource. {DESCRIPTION}"
    )
)
class InnerSpacePlanAsset(Projection):
    filename: str = strawberry.field(description="Asset file name")
    content_type: str = strawberry.field(description="Image media type")
    width_px: float | None = strawberry.field(description="Image width in pixels")
    height_px: float | None = strawberry.field(description="Image height in pixels")
    scale_per_unit: float | None = strawberry.field(description="Plan units per metre, or per foot when imperial")
    image_scale: float | None = strawberry.field(description="The plan map's horizontal image scale, if sent")
    image_offset: list[float] | None = strawberry.field(description="The plan map's image offset (x, y)")
    unit: str = strawberry.field(description="Length unit of the result: metric or imperial")

    _columns = ["filename", "content_type", "width_px", "height_px"]
