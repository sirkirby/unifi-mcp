"""InnerSpace resource URIs, importable without registering a resource."""

PLAN_IMAGE_URI_TEMPLATE = "innerspace://plans/{plan_id}/image"


def plan_image_uri(plan_id: str) -> str:
    """The resource URI a floor plan's image is read from."""
    return PLAN_IMAGE_URI_TEMPLATE.format(plan_id=plan_id)
