"""Pydantic domain models for the Network controller surface.

One module per domain (e.g., ``acl.py``). Each module defines a
``BaseModel`` whose fields tag mutability via
``json_schema_extra={"mutable": False}`` on read-only fields, plus
translation helpers (``from_controller`` / ``to_controller_create`` /
``to_controller_update``).

These models are the single source of truth shared by the MCP tool
layer (``apps/network``) and the API server (``apps/api``).
"""
