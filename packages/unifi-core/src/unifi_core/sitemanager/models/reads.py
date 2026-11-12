"""Closed inventory/detail arguments for account-scoped API reads."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SiteManagerEmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class SiteManagerPageInput(SiteManagerEmptyInput):
    page_size: int | None = Field(default=None, ge=1, le=500)
    cursor: str | None = None

    @model_validator(mode="after")
    def page(self):
        from unifi_core.sitemanager.managers.inventory_manager import page_params

        page_params(self.page_size, self.cursor)
        return self


class SiteManagerDevicesInput(SiteManagerPageInput):
    host_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    updated_since: str | None = None

    @field_validator("host_ids")
    @classmethod
    def hosts(cls, value):
        if value is not None and any(not host.strip() for host in value):
            raise ValueError("Provide nonempty Site Manager host identifiers")
        return value

    @field_validator("updated_since")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            from unifi_core.sitemanager.managers.inventory_manager import rfc3339

            return rfc3339(value, "updated_since")
        return value


class SiteManagerHostInput(SiteManagerEmptyInput):
    host_id: str
    include_reported_state: bool = False

    @field_validator("host_id")
    @classmethod
    def identifier(cls, value):
        from unifi_core.sitemanager.managers.connection_manager import path_segment

        path_segment(value, "host")
        return value


class SiteManagerConfigInput(SiteManagerEmptyInput):
    config_id: str

    @field_validator("config_id")
    @classmethod
    def identifier(cls, value):
        from unifi_core.sitemanager.managers.connection_manager import path_segment

        path_segment(value, "configuration")
        return value
