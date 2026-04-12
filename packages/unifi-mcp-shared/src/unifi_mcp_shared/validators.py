"""Base validators for UniFi MCP resource operations."""

import logging
from typing import Any, Dict, Optional, Tuple

from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)


class ResourceValidator:
    """Base validator for UniFi resource creation.

    Validates parameters against a JSON Schema definition.

    Args:
        schema: JSON Schema to validate against
        resource_name: Human-readable name for error messages
    """

    def __init__(self, schema: Dict[str, Any], resource_name: str):
        self.schema = schema
        self.resource_name = resource_name

    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Validate parameters against schema.

        Args:
            params: The parameters to validate

        Returns:
            Tuple of (is_valid, error_message, validated_params)
        """
        try:
            validate(instance=params, schema=self.schema)
            # Apply schema-defined defaults for top-level properties absent from params
            result = dict(params)
            for key, prop_schema in self.schema.get("properties", {}).items():
                if key not in result and "default" in prop_schema:
                    result[key] = prop_schema["default"]
            return True, None, result
        except ValidationError as e:
            logger.error("%s validation error: %s", self.resource_name, e.message)
            return False, f"{self.resource_name} validation error: {e.message}", None
        except Exception as e:
            logger.error(
                "Unexpected error validating %s: %s",
                self.resource_name,
                str(e),
                exc_info=True,
            )
            return (
                False,
                f"Unexpected error validating {self.resource_name}: {str(e)}",
                None,
            )


def create_response(success: bool, data: Any = None, error: str = None) -> Dict[str, Any]:
    """Create a standardized response format for all creation operations.

    Args:
        success: Whether the operation was successful
        data: The data to include in the response (typically a resource ID or object)
        error: Error message if the operation failed

    Returns:
        A standardized response dictionary
    """
    response = {"success": success}

    if success and data is not None:
        if isinstance(data, str):
            response["id"] = data
        else:
            response["data"] = data

    if not success and error:
        response["error"] = error

    return response
