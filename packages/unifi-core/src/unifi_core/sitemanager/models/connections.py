"""Strict inputs for an API-managed Site Manager account connection."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class _ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    @field_validator("name", check_fields=False)
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError("Provide a nonempty connection name of at most 128 characters")
        return value

    @field_validator("site_manager_api_key", check_fields=False)
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Provide a nonempty Site Manager API key")
        return value


class SiteManagerConnectionCreate(_ConnectionInput):
    name: str
    site_manager_api_key: SecretStr = Field(repr=False)


class SiteManagerConnectionPatch(_ConnectionInput):
    # Defaults permit omission; validators reject explicit nulls.
    name: str = None  # type: ignore[assignment]
    site_manager_api_key: SecretStr = Field(default=None, repr=False)  # type: ignore[assignment]
