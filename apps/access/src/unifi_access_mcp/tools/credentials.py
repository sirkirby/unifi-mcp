"""Credential tools for UniFi Access MCP server.

Provides tools for listing, inspecting, creating, and revoking access
credentials (NFC cards, PINs, mobile credentials).
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_access_mcp.runtime import credential_manager, server
from unifi_core.access.models._actions import RevokeCredentialInput
from unifi_core.access.models.credentials import (
    Credential,
    from_controller as credential_from_controller,
    to_controller_create as credential_to_controller_create,
)
from unifi_core.confirmation import create_preview, preview_response
from unifi_core.exceptions import UniFiNotFoundError

logger = logging.getLogger(__name__)


@server.tool(
    name="access_list_credentials",
    description=(
        "Lists all access credentials (NFC cards, PINs, mobile credentials) with their type, status, and assigned user."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="credential",
    permission_action="read",
    auth="local_only",
)
async def access_list_credentials() -> Dict[str, Any]:
    """List all credentials."""
    logger.info("access_list_credentials tool called")
    try:
        raw_list = await credential_manager.list_credentials()
        credentials = [
            credential_from_controller(raw).model_dump(exclude_none=True)
            for raw in raw_list
        ]
        return {"success": True, "data": {"credentials": credentials, "count": len(credentials)}}
    except Exception as e:
        logger.error("Error listing credentials: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list credentials: {e}"}


@server.tool(
    name="access_get_credential",
    description=(
        "Returns detailed information for a single access credential "
        "including type, status, assigned user, and creation date."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="credential",
    permission_action="read",
    auth="local_only",
)
async def access_get_credential(
    credential_id: Annotated[str, Field(description="Credential UUID (from access_list_credentials)")],
) -> Dict[str, Any]:
    """Get detailed credential information by ID."""
    logger.info("access_get_credential tool called for %s", credential_id)
    try:
        raw = await credential_manager.get_credential(credential_id)
        shaped = credential_from_controller(raw).model_dump(exclude_none=True)
        return {"success": True, "data": shaped}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting credential %s: %s", credential_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get credential: {e}"}


@server.tool(
    name="access_create_credential",
    description=(
        "Create a new access credential (NFC card, PIN, or mobile credential) "
        "and assign it to a user. Requires confirm=true to execute. "
        "Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="credential",
    permission_action="create",
    auth="local_only",
)
async def access_create_credential(
    credential_type: Annotated[
        str,
        Field(description="Type of credential to create: nfc, pin, or mobile."),
    ],
    credential_data: Annotated[
        dict,
        Field(
            description=(
                "Credential payload. Required fields depend on type: "
                "nfc: {user_id, token}, "
                "pin: {user_id, pin_code}, "
                "mobile: {user_id}."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, creates the credential. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Create a credential with preview/confirm."""
    logger.info("access_create_credential tool called (type=%s, confirm=%s)", credential_type, confirm)
    try:
        if not credential_data:
            return {"success": False, "error": "No credential data provided."}

        # Shape and validate inputs via the canonical Credential model
        try:
            model = Credential(
                type=credential_type,
                user_id=credential_data.get("user_id"),
                token=credential_data.get("token"),
                pin_code=credential_data.get("pin_code"),
            )
        except Exception as e:
            return {"success": False, "error": f"Invalid credential input: {e}"}

        payload = credential_to_controller_create(model)
        cred_type = payload["credential_type"]
        cred_data = payload["data"]

        if confirm:
            result = await credential_manager.apply_create_credential(cred_type, cred_data)
            return {"success": True, "data": result}

        preview_data = await credential_manager.create_credential(cred_type, cred_data)
        return create_preview(
            resource_type="access_credential",
            resource_data=preview_data["proposed_changes"],
            resource_name=f"{credential_type} credential",
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error creating credential: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to create credential: {e}"}


@server.tool(
    name="access_revoke_credential",
    description=(
        "Revoke (delete) an access credential. This permanently removes the "
        "credential from the system. Requires confirm=true to execute. "
        "Only available via local proxy session."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="credential",
    permission_action="delete",
    auth="local_only",
)
async def access_revoke_credential(
    credential_id: Annotated[str, Field(description="Credential UUID (from access_list_credentials)")],
    confirm: Annotated[
        bool,
        Field(description="When true, revokes the credential. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Revoke a credential with preview/confirm."""
    logger.info("access_revoke_credential tool called for %s (confirm=%s)", credential_id, confirm)
    try:
        try:
            params = RevokeCredentialInput(credential_id=credential_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        credential_id = params.credential_id

        if confirm:
            result = await credential_manager.apply_revoke_credential(credential_id)
            return {"success": True, "data": result}

        preview_data = await credential_manager.revoke_credential(credential_id)
        return preview_response(
            action="revoke",
            resource_type="access_credential",
            resource_id=credential_id,
            current_state=preview_data["current_state"],
            proposed_changes=preview_data["proposed_changes"],
            warnings=["This will permanently remove the credential. The user will lose access via this credential."],
        )
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error revoking credential %s: %s", credential_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to revoke credential: {e}"}


logger.info(
    "Credential tools registered: access_list_credentials, access_get_credential, "
    "access_create_credential, access_revoke_credential"
)
