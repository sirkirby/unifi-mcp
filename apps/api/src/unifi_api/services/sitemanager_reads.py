"""One validated account read path for REST, GraphQL and actions; no read auditing."""

import json
from dataclasses import dataclass, field

from unifi_core.exceptions import UniFiValidationError
from unifi_core.sitemanager.models.isp_metrics import SiteManagerMetricsGetInput, SiteManagerMetricsQueryInput
from unifi_core.sitemanager.models.reads import (
    SiteManagerConfigInput,
    SiteManagerDevicesInput,
    SiteManagerEmptyInput,
    SiteManagerHostInput,
    SiteManagerPageInput,
)

from unifi_api.services.actions import _validate_action_args
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
from unifi_api.services.manifest import ToolNotFound
from unifi_api.services.sitemanager_errors import SiteManagerAPIError, map_error

INPUTS = {
    "sitemanager_list_hosts": SiteManagerPageInput,
    "sitemanager_get_host": SiteManagerHostInput,
    "sitemanager_list_sites": SiteManagerPageInput,
    "sitemanager_list_devices": SiteManagerDevicesInput,
    "sitemanager_get_isp_metrics": SiteManagerMetricsGetInput,
    "sitemanager_query_isp_metrics": SiteManagerMetricsQueryInput,
    "sitemanager_list_sdwan_configs": SiteManagerEmptyInput,
    "sitemanager_get_sdwan_config": SiteManagerConfigInput,
    "sitemanager_get_sdwan_config_status": SiteManagerConfigInput,
}
PAGED = frozenset({"sitemanager_list_hosts", "sitemanager_list_sites", "sitemanager_list_devices"})


@dataclass
class AccountReadResult:
    data: object
    kind: str
    render_hint: dict
    connection_id: str
    revision: int
    meta: dict = field(default_factory=dict)

    def dict_data(self):
        if isinstance(self.data, list):
            return [item.to_dict() for item in self.data]
        return self.data.to_dict()

    def rest(self):
        if isinstance(self.data, list):
            return {"items": self.dict_data(), **self.meta, "render_hint": self.render_hint}
        if self.kind == "query":
            return {**self.dict_data(), "render_hint": self.render_hint}
        return {"data": self.dict_data(), "render_hint": self.render_hint}

    def action(self):
        result = {"success": True, "data": self.dict_data(), "render_hint": self.render_hint}
        if self.meta:
            result["meta"] = self.meta
        return result


def account_entry(registry, name):
    try:
        entry = registry.resolve(name)
    except ToolNotFound:
        raise SiteManagerAPIError(
            404, "sitemanager_tool_not_found", "Site Manager read operation was not found."
        ) from None
    if entry.connection_kind != "sitemanager_account" or entry.product != "sitemanager":
        raise SiteManagerAPIError(
            409, "sitemanager_target_mismatch", "Use the console action endpoint for this operation."
        )
    if entry.permission_action != "read" or entry.read_only_hint is not True or entry.auth_method != "api_key_only":
        raise SiteManagerAPIError(409, "sitemanager_target_mismatch", "Site Manager operations must be read-only.")
    return entry


async def read_sitemanager(*, registry, type_registry, factory, tool_name, args, redact_sensitive=True, cache=None):
    connection_id = None
    operation = "read Site Manager data"
    try:
        entry = account_entry(registry, tool_name)
        operation = entry.name.removeprefix("sitemanager_").replace("_", " ") + " from Site Manager"
        try:
            _validate_action_args(entry, args)
        except ValueError:
            raise UniFiValidationError("Invalid Site Manager arguments") from None
        model = INPUTS[entry.name].model_validate(args)
        effective = model.model_dump(exclude_none=True)
        translator = DISPATCH_ARG_TRANSLATORS.get(entry.name)
        positional, keyword = translator(effective) if translator is not None else ((), effective)
        projection, kind = type_registry.lookup_tool(entry.name)
        async with factory.acquire() as bundle:
            connection_id = bundle.connection_id

            async def fetch():
                manager = getattr(bundle, entry.manager_attr)
                raw = await getattr(manager, entry.manager_method)(*positional, **keyword)
                meta = {}
                if entry.name in PAGED:
                    items, token = raw
                    data = [projection.from_manager_output(item, redact_sensitive=redact_sensitive) for item in items]
                    meta["next_cursor"] = token
                elif kind == "list":
                    data = [projection.from_manager_output(item, redact_sensitive=redact_sensitive) for item in raw]
                    meta["next_cursor"] = None
                    if entry.name == "sitemanager_get_isp_metrics":
                        meta["count"] = len(data)
                else:
                    data = projection.from_manager_output(raw, redact_sensitive=redact_sensitive)
                result_kind = "query" if entry.name == "sitemanager_query_isp_metrics" else kind
                return AccountReadResult(
                    data, result_kind, projection.render_hint(kind), bundle.connection_id, bundle.revision, meta
                )

            key = json.dumps(
                [bundle.connection_id, bundle.revision, entry.name, effective, redact_sensitive],
                sort_keys=True,
                separators=(",", ":"),
            )
            return await cache.get_or_fetch(key, fetch) if cache is not None else await fetch()
    except Exception as exc:
        # Includes validation, projection and local construction failures. Never keep raw error text.
        error = map_error(exc, operation)
    error.connection_id = connection_id
    raise error from None
