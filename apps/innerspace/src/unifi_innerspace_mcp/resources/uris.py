"""InnerSpace resource URIs, importable without registering a resource."""

PLAN_IMAGE_URI_TEMPLATE = "innerspace://plans/{plan_id}/image"
PLAN_JPEG_URI_TEMPLATE = "innerspace://plans/{plan_id}/image.jpg"

# One template per image type, since a resource template declares a single MIME type:
# content type -> (type name, URI template).
PLAN_IMAGE_TYPES = {"image/png": ("PNG", PLAN_IMAGE_URI_TEMPLATE), "image/jpeg": ("JPEG", PLAN_JPEG_URI_TEMPLATE)}


def plan_image_uri(plan_id: str, content_type: str = "image/png") -> str | None:
    """The resource URI a floor plan's image of ``content_type`` is read from; ``None`` for a type none serves."""
    entry = PLAN_IMAGE_TYPES.get(content_type)
    return entry[1].format(plan_id=plan_id) if entry else None
