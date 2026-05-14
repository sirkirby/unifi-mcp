"""FastAPI app factory."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from strawberry.http import GraphQLHTTPResponse
from strawberry.types import ExecutionResult

from unifi_api._version import __version__ as _api_version
from unifi_api.auth.cache import ArgonVerifyCache
from unifi_api.config import ApiConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.engine import create_engine
from unifi_api.db.session import get_sessionmaker
from unifi_api.graphql.context import GraphQLContext, RequestCache
from unifi_api.graphql.errors import format_graphql_error
from unifi_api.graphql.schema import schema as graphql_schema
from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_api.logging import attach_rotating_file_handler, request_id_ctx
from unifi_api.routes import actions as actions_routes
from unifi_api.routes import admin_data as admin_data_routes
from unifi_api.routes import audit as audit_routes
from unifi_api.routes import catalog as catalog_routes
from unifi_api.routes import controllers as controllers_routes
from unifi_api.routes import health
from unifi_api.routes.admin import audit as admin_audit_routes
from unifi_api.routes.admin import auth as admin_auth_routes
from unifi_api.routes.admin import controllers as admin_controllers_routes
from unifi_api.routes.admin import dashboard as admin_dashboard_routes
from unifi_api.routes.admin import keys as admin_keys_routes
from unifi_api.routes.admin import logs as admin_logs_routes
from unifi_api.routes.admin import settings as admin_settings_routes
from unifi_api.routes.resources.access import (
    credentials as access_credentials_routes,
)
from unifi_api.routes.resources.access import (
    devices as access_devices_routes,
)
from unifi_api.routes.resources.access import (
    doors as access_doors_routes,
)
from unifi_api.routes.resources.access import (
    events as access_events_routes,
)
from unifi_api.routes.resources.access import (
    policies as access_policies_routes,
)
from unifi_api.routes.resources.access import (
    schedules as access_schedules_routes,
)
from unifi_api.routes.resources.access import (
    system as access_system_routes,
)
from unifi_api.routes.resources.access import (
    users as access_users_routes,
)
from unifi_api.routes.resources.access import (
    visitors as access_visitors_routes,
)
from unifi_api.routes.resources.network import (
    acl as net_acl_routes,
)
from unifi_api.routes.resources.network import (
    ap_groups as net_ap_groups_routes,
)
from unifi_api.routes.resources.network import (
    blocked_clients as net_blocked_clients_routes,
)
from unifi_api.routes.resources.network import (
    client_groups as net_client_groups_routes,
)
from unifi_api.routes.resources.network import (
    clients as net_clients_routes,
)
from unifi_api.routes.resources.network import (
    content_filters as net_content_filters_routes,
)
from unifi_api.routes.resources.network import (
    devices as net_devices_routes,
)
from unifi_api.routes.resources.network import (
    dns as net_dns_routes,
)
from unifi_api.routes.resources.network import (
    dpi as net_dpi_routes,
)
from unifi_api.routes.resources.network import (
    events as net_events_routes,
)
from unifi_api.routes.resources.network import (
    firewall_groups as net_firewall_groups_routes,
)
from unifi_api.routes.resources.network import (
    firewall_rules as net_firewall_routes,
)
from unifi_api.routes.resources.network import (
    firewall_zones as net_firewall_zones_routes,
)
from unifi_api.routes.resources.network import (
    lldp as net_lldp_routes,
)
from unifi_api.routes.resources.network import (
    lookup as net_lookup_routes,
)
from unifi_api.routes.resources.network import (
    networks as net_networks_routes,
)
from unifi_api.routes.resources.network import (
    oon as net_oon_routes,
)
from unifi_api.routes.resources.network import (
    port_forwards as net_port_forwards_routes,
)
from unifi_api.routes.resources.network import (
    qos as net_qos_routes,
)
from unifi_api.routes.resources.network import (
    rogue_aps as net_rogue_aps_routes,
)
from unifi_api.routes.resources.network import (
    routes as net_routes_routes,
)
from unifi_api.routes.resources.network import (
    snmp as net_snmp_routes,
)
from unifi_api.routes.resources.network import (
    speedtest as net_speedtest_routes,
)
from unifi_api.routes.resources.network import (
    stats as net_stats_routes,
)
from unifi_api.routes.resources.network import (
    switch as net_switch_routes,
)
from unifi_api.routes.resources.network import (
    system as net_system_routes,
)
from unifi_api.routes.resources.network import (
    user_groups as net_user_groups_routes,
)
from unifi_api.routes.resources.network import (
    vouchers as net_vouchers_routes,
)
from unifi_api.routes.resources.network import (
    vpn as net_vpn_routes,
)
from unifi_api.routes.resources.network import (
    wireless as net_wireless_routes,
)
from unifi_api.routes.resources.network import (
    wlans as net_wlans_routes,
)
from unifi_api.routes.resources.protect import (
    cameras as protect_cameras_routes,
)
from unifi_api.routes.resources.protect import (
    chimes as protect_chimes_routes,
)
from unifi_api.routes.resources.protect import (
    events as protect_events_routes,
)
from unifi_api.routes.resources.protect import (
    lights as protect_lights_routes,
)
from unifi_api.routes.resources.protect import (
    liveviews as protect_liveviews_routes,
)
from unifi_api.routes.resources.protect import (
    recognition as protect_recognition_routes,
)
from unifi_api.routes.resources.protect import (
    recordings as protect_recordings_routes,
)
from unifi_api.routes.resources.protect import (
    sensors as protect_sensors_routes,
)
from unifi_api.routes.resources.protect import (
    system as protect_system_routes,
)
from unifi_api.routes.streams import (
    access as access_streams_routes,
)
from unifi_api.routes.streams import (
    access_per_door as access_per_door_routes,
)
from unifi_api.routes.streams import (
    network as net_streams_routes,
)
from unifi_api.routes.streams import (
    network_per_device as net_per_device_routes,
)
from unifi_api.routes.streams import (
    protect as protect_streams_routes,
)
from unifi_api.routes.streams import (
    protect_per_camera as protect_per_camera_routes,
)
from unifi_api.serializers._registry import discover_serializers
from unifi_api.services.audit_pruner import prune_audit
from unifi_api.services.capability_cache import CapabilityCache
from unifi_api.services.controllers import list_controllers
from unifi_api.services.log_reader import LogReader
from unifi_api.services.managers import ManagerFactory
from unifi_api.services.manifest import ManifestRegistry
from unifi_api.services.settings import SettingsService
from unifi_api.services.streams import SubscriberPool

_streams_log = logging.getLogger("unifi-api.streams")


class _UnifiGraphQLRouter(GraphQLRouter):
    """GraphQLRouter that formats every error through `format_graphql_error`.

    Strawberry 0.315.3's `GraphQLRouter.__init__` does not accept an
    `error_formatter` kwarg, so we override `process_result` instead. The
    schema's own `process_errors` still runs (logging the full GraphQLError);
    we just rewrite the wire-level shape here.
    """

    async def process_result(self, request: Request, result: ExecutionResult) -> GraphQLHTTPResponse:
        data: GraphQLHTTPResponse = {"data": result.data}
        if result.errors:
            data["errors"] = [format_graphql_error(err) for err in result.errors]
        if result.extensions:
            data["extensions"] = result.extensions
        return data


def create_app(config: ApiConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup — manifest registry is loaded eagerly in create_app so it's
        # available even when the lifespan isn't run (e.g. ASGITransport tests).
        # Loading is idempotent and fast (file reads), so re-loading here keeps
        # the lifespan as the canonical startup hook.
        app.state.manifest_registry = ManifestRegistry.load_from_apps()

        # Phase 4B: eagerly start event listening for every (controller, product)
        # pair so SSE subscribers see a warm buffer on first connect. Failures
        # are logged warnings; they don't block startup. The stream endpoint for
        # a failed controller serves an empty buffer + tail of nothing.
        sm = app.state.sessionmaker
        try:
            async with sm() as session:
                controllers = await list_controllers(session)
        except Exception:
            controllers = []
            _streams_log.warning(
                "could not list controllers for eager start_listening",
                exc_info=True,
            )
        for controller in controllers:
            for product in [p for p in controller.product_kinds.split(",") if p]:
                try:
                    async with sm() as session:
                        mgr = await app.state.manager_factory.get_domain_manager(
                            session,
                            controller.id,
                            product,
                            "event_manager",
                        )
                    if hasattr(mgr, "start_listening"):
                        # Background-launch: aiounifi's start_websocket awaits
                        # its own message loop, so awaiting here blocks the
                        # whole lifespan. The WS subscription is best-effort
                        # warm-up for SSE consumers; failing it must not
                        # delay HTTP readiness.
                        async def _bg_start(c_id: str, p: str, m=mgr) -> None:
                            try:
                                await m.start_listening()
                                _streams_log.info(
                                    "[streams] start_listening ok for %s/%s",
                                    c_id,
                                    p,
                                )
                            except Exception:
                                _streams_log.warning(
                                    "[streams] start_listening failed for %s/%s",
                                    c_id,
                                    p,
                                    exc_info=True,
                                )

                        asyncio.create_task(
                            _bg_start(controller.id, product),
                            name=f"start_listening:{controller.id}/{product}",
                        )
                except Exception:
                    _streams_log.warning(
                        "[streams] start_listening setup failed for %s/%s",
                        controller.id,
                        product,
                        exc_info=True,
                    )

        # Phase 5B: file logging (optional) + background audit pruner
        settings_svc = app.state.settings_service
        log_enabled = await settings_svc.get_bool("logs.file.enabled", default=True)
        log_path = None
        if log_enabled:
            log_path_str = await settings_svc.get_str("logs.file.path", default="state/api.log")
            db_dir = Path(config.db.path).parent
            log_path = Path(log_path_str) if Path(log_path_str).is_absolute() else (db_dir / log_path_str).resolve()
            max_bytes = await settings_svc.get_int("logs.file.max_bytes", default=10 * 1024 * 1024)
            backup_count = await settings_svc.get_int("logs.file.backup_count", default=5)
            level = await settings_svc.get_str("logs.file.level", default="INFO")
            attach_rotating_file_handler(
                path=log_path,
                max_bytes=max_bytes,
                backup_count=backup_count,
                level=level,
            )
            app.state.log_file_path = log_path
            app.state.log_reader = LogReader(log_path)

        # Background audit pruner — periodic prune based on settings
        async def _prune_loop():
            while True:
                try:
                    interval_h = await settings_svc.get_int(
                        "audit.retention.prune_interval_hours",
                        default=6,
                    )
                    enabled = await settings_svc.get_bool(
                        "audit.retention.enabled",
                        default=True,
                    )
                    if enabled:
                        max_age = await settings_svc.get_int(
                            "audit.retention.max_age_days",
                            default=90,
                        )
                        max_rows = await settings_svc.get_int(
                            "audit.retention.max_rows",
                            default=1_000_000,
                        )
                        result = await prune_audit(
                            app.state.sessionmaker,
                            max_age_days=max_age,
                            max_rows=max_rows,
                        )
                        _streams_log.info(
                            "[audit-pruner] pruned %s rows; current count %s",
                            result["pruned"],
                            result["current_count"],
                        )
                except Exception:
                    _streams_log.warning("[audit-pruner] error", exc_info=True)
                await asyncio.sleep(interval_h * 3600)

        app.state._audit_pruner_task = asyncio.create_task(_prune_loop())

        yield
        # Cancel background pruner task
        task = getattr(app.state, "_audit_pruner_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # Shutdown — drop manager caches first, then engine
        factory = app.state.manager_factory
        cached_ids = list({k[0] for k in factory._connection_cache.keys()})
        for cid in cached_ids:
            await factory.invalidate_controller(cid)
        await app.state.engine.dispose()

    app = FastAPI(
        title="unifi-api",
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        lifespan=lifespan,
    )

    # Auth doesn't use FastAPI's HTTPBearer dependency (the middleware reads
    # the header directly to keep the audit-on-failure path simple), so the
    # generated OpenAPI schema has no security info — which means Swagger UI
    # at /v1/docs has no "Authorize" button. Inject a bearer scheme manually
    # and mark it as the global default so "Try it out" can authenticate.
    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["ApiKeyAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "Paste your admin / write / read scoped API key "
                "(starts with `unifi_live_…` or `unifi_test_…`). "
                "Click 'Authorize' once and Swagger UI will send the "
                "Bearer header on every request."
            ),
        }
        schema["security"] = [{"ApiKeyAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    if config.http.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.http.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_ctx.reset(token)

    # Wire DB
    # Validate the encryption key exists at startup; service refuses to start without it.
    db_key = ApiConfig.read_db_key()
    engine = create_engine(config.db.path)
    app.state.engine = engine
    app.state.sessionmaker = get_sessionmaker(engine)

    cipher = ColumnCipher(derive_key(db_key))
    app.state.cipher = cipher
    app.state.manager_factory = ManagerFactory(app.state.sessionmaker, cipher)
    app.state.subscriber_pool = SubscriberPool()
    app.state.argon_cache = ArgonVerifyCache()
    app.state.capability_cache = CapabilityCache()
    app.state.settings_service = SettingsService(app.state.sessionmaker)
    app.state.db_path = config.db.path
    app.state.api_version = _api_version
    app.state.started_at = datetime.now(timezone.utc)
    app.state.log_file_path = None  # Task 11 may override this if log file is enabled
    app.state.log_reader = LogReader(Path("/dev/null"))  # Task 11 may override
    app.state.manifest_registry = ManifestRegistry.load_from_apps()
    manifest_tool_names = set(app.state.manifest_registry.all_tools())

    # Phase 6 close — every read tool/resource is projected via a Strawberry
    # type. The type_registry is populated first so it can be passed to
    # discover_serializers() below; the manifest validation step requires
    # every tool to have either a serializer (mutation) or a type (read).
    app.state.type_registry = build_type_registry()

    # Discover and register every serializer module (mutation tools), then
    # validate against the full manifest. Phase 6 close: every manifest tool
    # must have either a serializer (mutation) or a type (read). The CI gate
    # test_every_tool_has_a_serializer enforces the same invariant.
    app.state.serializer_registry = discover_serializers(
        manifest_tool_names,
        type_registry=app.state.type_registry,
    )

    app.include_router(health.router, prefix="/v1")
    app.include_router(controllers_routes.router, prefix="/v1")
    app.include_router(actions_routes.router, prefix="/v1")
    app.include_router(catalog_routes.router, prefix="/v1")
    app.include_router(audit_routes.router, prefix="/v1")
    app.include_router(admin_data_routes.router, prefix="/v1")
    for r in (
        net_clients_routes,
        net_devices_routes,
        net_networks_routes,
        net_firewall_routes,
        net_wlans_routes,
        net_switch_routes,
        net_lldp_routes,
        net_rogue_aps_routes,
        net_wireless_routes,
        net_speedtest_routes,
        net_blocked_clients_routes,
        net_client_groups_routes,
        net_user_groups_routes,
        net_lookup_routes,
        net_routes_routes,
        net_dns_routes,
        net_vpn_routes,
        net_ap_groups_routes,
        net_firewall_groups_routes,
        net_firewall_zones_routes,
        net_qos_routes,
        net_dpi_routes,
        net_content_filters_routes,
        net_acl_routes,
        net_oon_routes,
        net_port_forwards_routes,
        net_vouchers_routes,
        net_snmp_routes,
        # Cluster 6: stats / events / system. The network events router owns
        # the bare /events path for both products via a capability-aware
        # dispatcher; it must be included before protect_events_routes so the
        # network/protect-aware handler wins the path match.
        net_stats_routes,
        net_events_routes,
        net_system_routes,
    ):
        app.include_router(r.router, prefix="/v1")
    for r in (
        protect_cameras_routes,
        protect_events_routes,
        protect_recordings_routes,
        protect_lights_routes,
        protect_sensors_routes,
        protect_chimes_routes,
        protect_liveviews_routes,
        protect_recognition_routes,
        protect_system_routes,
    ):
        app.include_router(r.router, prefix="/v1")
    for r in (
        access_doors_routes,
        access_users_routes,
        access_credentials_routes,
        access_policies_routes,
        access_schedules_routes,
        access_devices_routes,
        access_visitors_routes,
        access_events_routes,
        access_system_routes,
    ):
        app.include_router(r.router, prefix="/v1")
    for r in (
        net_streams_routes,
        protect_streams_routes,
        access_streams_routes,
        net_per_device_routes,
        protect_per_camera_routes,
        access_per_door_routes,
    ):
        app.include_router(r.router, prefix="/v1")

    # Admin UI: static assets + auth routes (no /v1 prefix; lives under /admin/*)
    _static_dir = Path(__file__).parent / "static" / "admin"
    app.mount(
        "/admin/static",
        StaticFiles(directory=str(_static_dir)),
        name="admin-static",
    )
    app.include_router(admin_auth_routes.router)
    app.include_router(admin_dashboard_routes.router)
    app.include_router(admin_keys_routes.router)
    app.include_router(admin_controllers_routes.router)
    app.include_router(admin_audit_routes.router)
    app.include_router(admin_logs_routes.router)
    app.include_router(admin_settings_routes.router)

    async def _graphql_context(request: Request) -> GraphQLContext:
        """Build per-request GraphQLContext.

        Auth is enforced by Strawberry permission classes (IsRead/IsAdmin) on
        each field. The context here just exposes the api_key info if a valid
        Bearer was supplied; permission classes deny when scopes are empty.

        The REST auth path raises HTTPException(401) on failure — we catch
        that here so GraphQL stays HTTP 200 (with errors[] populated by the
        permission denial path), matching GraphQL conventions.
        """
        api_key_scopes = ""
        api_key_id: str | None = None
        api_key_prefix: str | None = None
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            from unifi_api.auth.middleware import _authenticate

            try:
                row = await _authenticate(request)
                api_key_id = row.id
                api_key_scopes = row.scopes
                api_key_prefix = row.prefix
            except Exception:
                # Auth failed — leave scopes empty so permission classes deny.
                pass
        return GraphQLContext(
            cache=RequestCache(),
            sessionmaker=app.state.sessionmaker,
            manager_factory=app.state.manager_factory,
            api_key_id=api_key_id,
            api_key_scopes=api_key_scopes,
            api_key_prefix=api_key_prefix,
        )

    graphql_app = _UnifiGraphQLRouter(
        graphql_schema,
        context_getter=_graphql_context,
        graphql_ide="graphiql",
    )
    app.include_router(graphql_app, prefix="/v1/graphql")

    return app
