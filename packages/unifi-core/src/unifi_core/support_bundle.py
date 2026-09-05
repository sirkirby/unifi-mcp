"""Privacy kernel for community-shareable UniFi support bundles.

Support bundles are intentionally stricter than operator diagnostics.  This
module never reads logs, environment variables, files, or controller APIs.  It
accepts already-available values, emits a closed typed schema, and reduces
resource objects to allowlisted structure without serializing scalar values.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from itertools import islice
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiPermissionError,
    UniFiRateLimitError,
)
from unifi_core.redaction import is_sensitive_key

SUPPORT_BUNDLE_SCHEMA_VERSION = 1
SUPPORT_SANITIZER_POLICY = "unifi-support-bundle"
SUPPORT_SANITIZER_VERSION = 1
MAX_BUNDLE_BYTES = 32 * 1024
MAX_COLLECTION_ITEMS = 100
MAX_DEPTH = 6
MAX_FIELDS_PER_OBJECT = 64
MAX_FIELD_NAME_LENGTH = 96
MAX_VERSION_LENGTH = 64
MAX_NODES = 2_000
MAX_SHAPE_VARIANTS = 16
SHARING_NOTICE = "Review this bundle before posting it publicly."

_VERSION_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+){0,7}(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?"
    r"(?:\+[0-9a-z]+(?:\.[0-9a-z]+)*)?$"
)
_PYTHON_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RFC3339_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$")
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class Product(str, Enum):
    NETWORK = "network"
    PROTECT = "protect"
    ACCESS = "access"


class EvidenceStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_CONNECTED = "not_connected"
    NOT_CONFIGURED = "not_configured"
    UNSUPPORTED = "unsupported"
    PROBE_FAILED = "probe_failed"


class AttemptStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    NOT_CONFIGURED = "not_configured"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ErrorCategory(str, Enum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class RemediationCode(str, Enum):
    CHECK_CREDENTIALS = "check_credentials"
    CHECK_PERMISSIONS = "check_permissions"
    WAIT_AND_RETRY = "wait_and_retry"
    CHECK_CONNECTIVITY = "check_connectivity"
    UPDATE_DEPENDENCIES = "update_dependencies"


class PathMode(str, Enum):
    OBJECT_FIELDS = "object_fields"
    IDENTIFIER_MAP = "identifier_map"
    VALUE_MAP = "value_map"
    OPAQUE = "opaque"


class ShapeKind(str, Enum):
    SCALAR = "scalar"
    OBJECT = "object"
    SEQUENCE = "sequence"
    IDENTIFIER_MAP = "identifier_map"
    VALUE_MAP = "value_map"
    OPAQUE = "opaque"


class ScalarType(str, Enum):
    NULL = "null"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    DATETIME = "datetime"
    ENUM = "enum"
    UNKNOWN = "unknown"


class CountBucket(str, Enum):
    ZERO = "0"
    ONE = "1"
    TWO_TO_FIVE = "2-5"
    SIX_TO_TWENTY = "6-20"
    TWENTY_ONE_TO_ONE_HUNDRED = "21-100"
    OVER_ONE_HUNDRED = "100+"


class ServerFeatureFlag(str, Enum):
    DIAGNOSTICS_ENABLED = "diagnostics_enabled"
    DIAGNOSTICS_DISABLED = "diagnostics_disabled"
    RESPONSE_REDACTION_ENABLED = "response_redaction_enabled"
    RESPONSE_REDACTION_DISABLED = "response_redaction_disabled"


class DependencyPackage(str, Enum):
    AIOUNIFI = "aiounifi"
    MCP = "mcp"
    PYDANTIC = "pydantic"
    PY_UNIFI_ACCESS = "py-unifi-access"
    UNIFI_ACCESS_MCP = "unifi-access-mcp"
    UNIFI_CORE = "unifi-core"
    UNIFI_MCP_SHARED = "unifi-mcp-shared"
    UNIFI_NETWORK_MCP = "unifi-network-mcp"
    UNIFI_PROTECT_MCP = "unifi-protect-mcp"
    UIPROTECT = "uiprotect"


class ControllerCapabilityFlag(str, Enum):
    CACHED_STATE = "cached_state"


def count_bucket(value: int) -> CountBucket:
    """Return a coarse, non-identifying count bucket."""
    if value <= 0:
        return CountBucket.ZERO
    if value == 1:
        return CountBucket.ONE
    if value <= 5:
        return CountBucket.TWO_TO_FIVE
    if value <= 20:
        return CountBucket.SIX_TO_TWENTY
    if value <= 100:
        return CountBucket.TWENTY_ONE_TO_ONE_HUNDRED
    return CountBucket.OVER_ONE_HUNDRED


class SafeConnectionAttempt(_ClosedModel):
    status: AttemptStatus = AttemptStatus.NOT_ATTEMPTED
    error_category: ErrorCategory | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    remediation: RemediationCode | None = None

    @model_validator(mode="after")
    def _failure_fields_match_status(self) -> SafeConnectionAttempt:
        has_failure = self.error_category is not None or self.http_status is not None or self.remediation is not None
        if self.status is AttemptStatus.FAILED and (self.error_category is None or self.remediation is None):
            raise ValueError("failed attempts require an error category and remediation")
        if self.status is not AttemptStatus.FAILED and has_failure:
            raise ValueError("only failed attempts may contain failure details")
        return self


def _safe_http_status(exc: BaseException) -> int | None:
    try:
        status = getattr(exc, "status", None)
    except Exception:
        return None
    return status if isinstance(status, int) and 100 <= status <= 599 else None


def classify_error(exc: BaseException) -> tuple[ErrorCategory, int | None, RemediationCode]:
    """Classify an exception without reading or serializing its message."""
    status = _safe_http_status(exc)
    if status == 401 or isinstance(exc, UniFiAuthError):
        return ErrorCategory.AUTHENTICATION, status, RemediationCode.CHECK_CREDENTIALS
    if status == 403 or isinstance(exc, (UniFiPermissionError, PermissionError)):
        return ErrorCategory.PERMISSION, status, RemediationCode.CHECK_PERMISSIONS
    if status == 429 or isinstance(exc, UniFiRateLimitError):
        return ErrorCategory.RATE_LIMITED, status, RemediationCode.WAIT_AND_RETRY
    if isinstance(exc, (TimeoutError,)):
        return ErrorCategory.TIMEOUT, status, RemediationCode.CHECK_CONNECTIVITY
    if isinstance(exc, (UniFiConnectionError, ConnectionError, OSError)):
        return ErrorCategory.CONNECTION, status, RemediationCode.CHECK_CONNECTIVITY

    name = type(exc).__name__
    if name == "AuthenticationRateLimitError":
        return ErrorCategory.RATE_LIMITED, status, RemediationCode.WAIT_AND_RETRY
    if name in {"LoginRequired", "Unauthorized", "TwoFaTokenRequired"}:
        return ErrorCategory.AUTHENTICATION, status, RemediationCode.CHECK_CREDENTIALS
    if name in {"Forbidden", "NoPermission"}:
        return ErrorCategory.PERMISSION, status, RemediationCode.CHECK_PERMISSIONS
    if name in {"ServerDisconnectedError", "ClientConnectionError", "ClientConnectorError"}:
        return ErrorCategory.CONNECTION, status, RemediationCode.CHECK_CONNECTIVITY
    if name in {"ContentTypeError", "JSONDecodeError"}:
        return ErrorCategory.INVALID_RESPONSE, status, RemediationCode.UPDATE_DEPENDENCIES
    return ErrorCategory.UNKNOWN, status, RemediationCode.UPDATE_DEPENDENCIES


def connection_attempt_not_configured() -> dict[str, Any]:
    return SafeConnectionAttempt(status=AttemptStatus.NOT_CONFIGURED).model_dump(mode="json")


def connection_attempt_started() -> dict[str, Any]:
    return SafeConnectionAttempt(status=AttemptStatus.IN_PROGRESS).model_dump(mode="json")


def connection_attempt_succeeded() -> dict[str, Any]:
    return SafeConnectionAttempt(status=AttemptStatus.SUCCEEDED).model_dump(mode="json")


def connection_attempt_failed(exc: BaseException) -> dict[str, Any]:
    category, status, remediation = classify_error(exc)
    return SafeConnectionAttempt(
        status=AttemptStatus.FAILED,
        error_category=category,
        http_status=status,
        remediation=remediation,
    ).model_dump(mode="json")


class NetworkCapabilities(_ClosedModel):
    product: Literal["network"] = "network"
    session_available: bool
    integration_api_key_configured: bool
    controller_type: Literal["proxy", "direct", "auto", "unknown"]
    reconnect_circuit: Literal["open", "closed"]


class ProtectCapabilities(_ClosedModel):
    product: Literal["protect"] = "protect"
    session_available: bool
    bootstrap_available: bool
    public_api_key_configured: bool
    websocket_state: Literal["connected", "disconnected", "unknown"]


class AccessCapabilities(_ClosedModel):
    product: Literal["access"] = "access"
    developer_api_available: bool
    proxy_session_available: bool
    api_token_configured: bool


ConnectionCapabilities = Annotated[
    NetworkCapabilities | ProtectCapabilities | AccessCapabilities,
    Field(discriminator="product"),
]


class ConnectionSection(_ClosedModel):
    initialized: bool
    connected: bool
    tls_verification_enabled: bool
    last_attempt: SafeConnectionAttempt
    capabilities: ConnectionCapabilities


class ServerSection(_ClosedModel):
    package: Literal["unifi-network-mcp", "unifi-protect-mcp", "unifi-access-mcp"]
    version: str
    tool: Literal["unifi_get_support_bundle", "protect_get_support_bundle", "access_get_support_bundle"]
    schema_version: Literal[1] = SUPPORT_BUNDLE_SCHEMA_VERSION
    feature_flags: tuple[ServerFeatureFlag, ...] = ()

    @field_validator("version")
    @classmethod
    def _version_is_safe(cls, value: str) -> str:
        return _validated_version(value, "software version")

    @field_validator("feature_flags")
    @classmethod
    def _flags_are_safe(cls, values: tuple[ServerFeatureFlag, ...]) -> tuple[ServerFeatureFlag, ...]:
        if len(values) > 16:
            raise ValueError("feature_flags exceeds 16 entries")
        return tuple(sorted(set(values), key=lambda value: value.value))


class RuntimeSection(_ClosedModel):
    python_version: str
    os_family: Literal["linux", "macos", "windows", "other"]
    architecture: Literal["x86_64", "amd64", "arm64", "aarch64", "i386", "i686", "other"]
    transports: tuple[Literal["stdio", "streamable_http", "sse"], ...]
    registration_mode: Literal["meta_only", "lazy", "eager"]
    content_mode: Literal["json", "text", "dual"]
    manifest_tool_count: int = Field(ge=0, le=10_000)
    manifest_generator: Literal["scripts/generate_tool_manifest.py"]

    @field_validator("python_version")
    @classmethod
    def _python_version_is_safe(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) > MAX_VERSION_LENGTH:
            raise ValueError(f"Python version exceeds {MAX_VERSION_LENGTH} characters")
        return _validated(value, _PYTHON_VERSION_RE, "Python version")

    @field_validator("transports")
    @classmethod
    def _transports_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 3:
            raise ValueError("transports exceeds three entries")
        return tuple(sorted(set(values)))


class DependencySection(_ClosedModel):
    package: DependencyPackage
    version: str | Literal["not_installed"]

    @field_validator("version")
    @classmethod
    def _dependency_version_is_safe(cls, value: str) -> str:
        if value == "not_installed":
            return value
        return _validated_version(value, "dependency version")


class ControllerSection(_ClosedModel):
    status: EvidenceStatus
    application_version: str | None = None
    unifi_os_version: str | None = None
    api_surface: Literal["controller_v2", "integration", "alarm_manager_v2", "mixed", "unknown"]
    capability_flags: tuple[ControllerCapabilityFlag, ...] = ()

    @field_validator("application_version", "unifi_os_version")
    @classmethod
    def _controller_version_is_safe(cls, value: str | None) -> str | None:
        return None if value is None else _validated_version(value, "controller version")

    @field_validator("capability_flags")
    @classmethod
    def _controller_flags_are_safe(
        cls, values: tuple[ControllerCapabilityFlag, ...]
    ) -> tuple[ControllerCapabilityFlag, ...]:
        if len(values) > 32:
            raise ValueError("capability_flags exceeds 32 entries")
        return tuple(sorted(set(values), key=lambda value: value.value))


class ShapeField(_ClosedModel):
    name: str
    shape: StructuralShape

    @field_validator("name")
    @classmethod
    def _name_is_allowlist_grammar(cls, value: str) -> str:
        value = _validated(value, _FIELD_RE, "shape field")
        if is_sensitive_key(value):
            raise ValueError("shape fields cannot use secret-bearing names")
        return value


class StructuralShape(_ClosedModel):
    kind: ShapeKind
    scalar_type: ScalarType | None = None
    fields: tuple[ShapeField, ...] = ()
    variants: tuple[StructuralShape, ...] = ()
    item_count: CountBucket | None = None
    unknown_fields: CountBucket | None = None

    @model_validator(mode="after")
    def _shape_members_match_kind(self) -> StructuralShape:
        if self.kind is ShapeKind.SCALAR:
            if self.scalar_type is None:
                raise ValueError("scalar shapes require scalar_type")
            if self.fields or self.variants or self.item_count is not None or self.unknown_fields is not None:
                raise ValueError("scalar shapes cannot contain structural members")
        elif self.scalar_type is not None:
            raise ValueError("only scalar shapes may set scalar_type")
        if self.kind in {ShapeKind.OBJECT, ShapeKind.VALUE_MAP}:
            if self.variants or self.item_count is not None:
                raise ValueError("object shapes cannot contain collection members")
        elif self.kind in {ShapeKind.SEQUENCE, ShapeKind.IDENTIFIER_MAP}:
            if self.fields or self.unknown_fields is not None or self.item_count is None:
                raise ValueError("collection shapes require item_count and variants only")
        elif self.kind is ShapeKind.OPAQUE:
            if self.fields or self.variants or self.item_count is not None or self.unknown_fields is not None:
                raise ValueError("opaque shapes cannot contain structural members")
        if len(self.fields) > MAX_FIELDS_PER_OBJECT:
            raise ValueError(f"shape fields exceed {MAX_FIELDS_PER_OBJECT}")
        if len(self.variants) > MAX_SHAPE_VARIANTS:
            raise ValueError(f"shape variants exceed {MAX_SHAPE_VARIANTS}")
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError("shape field names must be unique")
        return self


class SummaryProbe(_ClosedModel):
    probe: Literal["summary"] = "summary"
    status: EvidenceStatus


class ConnectivityProbe(_ClosedModel):
    probe: Literal["connectivity"] = "connectivity"
    status: EvidenceStatus
    duration_bucket: Literal["under_100ms", "100ms_1s", "1s_5s", "over_5s", "unknown"]
    outcome: Literal["success", "authentication", "permission", "timeout", "connection", "unknown"]


ConnectivityOutcome = Literal["success", "authentication", "permission", "timeout", "connection", "unknown"]


def connectivity_http_outcome(status: int) -> ConnectivityOutcome:
    """Reduce an HTTP status to the fixed connectivity outcome vocabulary."""
    if 200 <= status < 300:
        return "success"
    if status == 401:
        return "authentication"
    if status == 403:
        return "permission"
    return "unknown"


def connectivity_probe_result(outcome: ConnectivityOutcome, duration_ms: float | None) -> ConnectivityProbe:
    """Build fixed, privacy-safe connectivity evidence from an outcome and elapsed time."""
    if duration_ms is None:
        duration_bucket = "unknown"
    elif duration_ms < 100:
        duration_bucket = "under_100ms"
    elif duration_ms < 1_000:
        duration_bucket = "100ms_1s"
    elif duration_ms < 5_000:
        duration_bucket = "1s_5s"
    else:
        duration_bucket = "over_5s"
    return ConnectivityProbe(
        status=EvidenceStatus.AVAILABLE if outcome == "success" else EvidenceStatus.UNAVAILABLE,
        duration_bucket=duration_bucket,
        outcome=outcome,
    )


class ResourceShapeProbe(_ClosedModel):
    probe: Literal["resource_shape"] = "resource_shape"
    status: EvidenceStatus
    resource: Literal["sensors"]
    shape: StructuralShape | None = None

    @model_validator(mode="after")
    def _available_shape_is_present(self) -> ResourceShapeProbe:
        if (self.status is EvidenceStatus.AVAILABLE) != (self.shape is not None):
            raise ValueError("resource_shape evidence is present only when status is available")
        return self


ProbeSection = Annotated[SummaryProbe | ConnectivityProbe | ResourceShapeProbe, Field(discriminator="probe")]


class SanitizerBounds(_ClosedModel):
    max_bundle_bytes: Literal[32768] = MAX_BUNDLE_BYTES
    max_collection_items: Literal[100] = MAX_COLLECTION_ITEMS
    max_depth: Literal[6] = MAX_DEPTH
    max_fields_per_object: Literal[64] = MAX_FIELDS_PER_OBJECT
    max_nodes: Literal[2000] = MAX_NODES
    max_shape_variants: Literal[16] = MAX_SHAPE_VARIANTS


class SanitizationSection(_ClosedModel):
    policy: Literal["unifi-support-bundle"] = SUPPORT_SANITIZER_POLICY
    version: Literal[1] = SUPPORT_SANITIZER_VERSION
    ordinary_response_redaction_ignored: Literal[True] = True
    values_suppressed: bool
    dynamic_keys_suppressed: bool
    errors_normalized: bool
    variants_truncated: bool
    nodes_truncated: bool
    bytes_truncated: bool
    bounds: SanitizerBounds = Field(default_factory=SanitizerBounds)
    raw_resource_values_included: Literal[False] = False


_SERVER_IDENTITIES: Final = MappingProxyType(
    {
        Product.NETWORK: ("unifi-network-mcp", "unifi_get_support_bundle"),
        Product.PROTECT: ("unifi-protect-mcp", "protect_get_support_bundle"),
        Product.ACCESS: ("unifi-access-mcp", "access_get_support_bundle"),
    }
)
_DEPENDENCIES_BY_PRODUCT: Final = MappingProxyType(
    {
        Product.NETWORK: frozenset(
            {
                DependencyPackage.AIOUNIFI,
                DependencyPackage.MCP,
                DependencyPackage.PYDANTIC,
                DependencyPackage.UNIFI_CORE,
                DependencyPackage.UNIFI_MCP_SHARED,
                DependencyPackage.UNIFI_NETWORK_MCP,
            }
        ),
        Product.PROTECT: frozenset(
            {
                DependencyPackage.MCP,
                DependencyPackage.PYDANTIC,
                DependencyPackage.UNIFI_CORE,
                DependencyPackage.UNIFI_MCP_SHARED,
                DependencyPackage.UNIFI_PROTECT_MCP,
                DependencyPackage.UIPROTECT,
            }
        ),
        Product.ACCESS: frozenset(
            {
                DependencyPackage.MCP,
                DependencyPackage.PYDANTIC,
                DependencyPackage.PY_UNIFI_ACCESS,
                DependencyPackage.UNIFI_ACCESS_MCP,
                DependencyPackage.UNIFI_CORE,
                DependencyPackage.UNIFI_MCP_SHARED,
            }
        ),
    }
)
# Gate 0 deferred every v1 resource-shape vocabulary.  A future entry must be
# keyed by sanitizer version, product, and resource, with exact path allowlists.
_RESOURCE_FIELD_VOCABULARIES: Final = MappingProxyType({})


class SupportBundle(_ClosedModel):
    schema_version: Literal[1] = SUPPORT_BUNDLE_SCHEMA_VERSION
    generated_at: str
    product: Product
    server: ServerSection
    runtime: RuntimeSection
    dependencies: tuple[DependencySection, ...]
    controller: ControllerSection
    connection: ConnectionSection
    probe: ProbeSection
    sanitization: SanitizationSection
    sharing_notice: Literal["Review this bundle before posting it publicly."] = SHARING_NOTICE

    @field_validator("generated_at")
    @classmethod
    def _timestamp_is_safe(cls, value: str) -> str:
        value = _validated(value, _RFC3339_UTC_RE, "generated_at")
        try:
            datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError("generated_at is not a valid UTC timestamp") from exc
        return value

    @model_validator(mode="after")
    def _products_match(self) -> SupportBundle:
        if self.product.value != self.connection.capabilities.product:
            raise ValueError("bundle product must match connection capabilities")
        expected_package, expected_tool = _SERVER_IDENTITIES[self.product]
        if (self.server.package, self.server.tool) != (expected_package, expected_tool):
            raise ValueError("server package and tool must match bundle product")
        if len(self.dependencies) > 8:
            raise ValueError("dependencies exceeds eight entries")
        packages = [dependency.package for dependency in self.dependencies]
        if len(packages) != len(set(packages)):
            raise ValueError("dependency package names must be unique")
        if packages != sorted(packages, key=lambda package: package.value):
            raise ValueError("dependencies must be sorted by package")
        if not set(packages).issubset(_DEPENDENCIES_BY_PRODUCT[self.product]):
            raise ValueError("dependency package is not allowed for bundle product")
        if isinstance(self.probe, ResourceShapeProbe) and self.probe.status is EvidenceStatus.AVAILABLE:
            vocabulary = _RESOURCE_FIELD_VOCABULARIES.get(
                (SUPPORT_SANITIZER_VERSION, self.product, self.probe.resource)
            )
            if vocabulary is None:
                raise ValueError("resource_shape is unsupported for this product and sanitizer version")
            _validate_shape_vocabulary(self.probe.shape, vocabulary, path=("resource",))
        return self


@dataclass(frozen=True)
class PathRule:
    mode: PathMode
    fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.mode in {PathMode.OBJECT_FIELDS, PathMode.VALUE_MAP} and not self.fields:
            raise ValueError(f"{self.mode.value} requires an explicit field allowlist")
        if len(self.fields) > MAX_FIELDS_PER_OBJECT:
            raise ValueError(f"path policies cannot allow more than {MAX_FIELDS_PER_OBJECT} fields")
        if self.mode in {PathMode.IDENTIFIER_MAP, PathMode.OPAQUE} and self.fields:
            raise ValueError(f"{self.mode.value} cannot contain a field allowlist")
        for field_name in self.fields:
            _validated(field_name, _FIELD_RE, "path-policy field")
            if is_sensitive_key(field_name):
                raise ValueError("path policies cannot allowlist secret-bearing field names")


@dataclass(frozen=True)
class StructuralExtraction:
    shape: StructuralShape
    sanitization: SanitizationSection


class _ExtractionState:
    def __init__(self) -> None:
        self.nodes = 0
        self.values_suppressed = False
        self.dynamic_keys_suppressed = False
        self.variants_truncated = False
        self.nodes_truncated = False


def extract_structural_shape(
    value: Any,
    *,
    policy: Mapping[tuple[str, ...], PathRule],
    root_path: tuple[str, ...] = ("resource",),
) -> StructuralExtraction:
    """Extract an allowlisted, value-free shape from controller-like data."""
    state = _ExtractionState()
    try:
        shape = _extract(value, path=root_path, policy=policy, state=state, depth=0, ancestors=frozenset())
    except Exception:
        # This boundary must never inspect or serialize the original exception.
        shape = StructuralShape(kind=ShapeKind.OPAQUE)
        state.values_suppressed = True
        state.nodes_truncated = True
        errors_normalized = True
    else:
        errors_normalized = False
    return StructuralExtraction(
        shape=shape,
        sanitization=SanitizationSection(
            values_suppressed=state.values_suppressed,
            dynamic_keys_suppressed=state.dynamic_keys_suppressed,
            errors_normalized=errors_normalized,
            variants_truncated=state.variants_truncated,
            nodes_truncated=state.nodes_truncated,
            bytes_truncated=False,
        ),
    )


def _extract(
    value: Any,
    *,
    path: tuple[str, ...],
    policy: Mapping[tuple[str, ...], PathRule],
    state: _ExtractionState,
    depth: int,
    ancestors: frozenset[int],
) -> StructuralShape:
    state.nodes += 1
    if state.nodes > MAX_NODES or depth > MAX_DEPTH:
        state.nodes_truncated = True
        state.values_suppressed = True
        return StructuralShape(kind=ShapeKind.OPAQUE)

    scalar_type = _scalar_type(value)
    if scalar_type is not None:
        state.values_suppressed = True
        return StructuralShape(kind=ShapeKind.SCALAR, scalar_type=scalar_type)

    object_id = id(value)
    if object_id in ancestors:
        state.nodes_truncated = True
        return StructuralShape(kind=ShapeKind.OPAQUE)
    next_ancestors = ancestors | {object_id}

    adapted = _adapt_object(value)
    if adapted is not None:
        value = adapted

    rule = policy.get(path)
    if rule is None or rule.mode is PathMode.OPAQUE:
        state.values_suppressed = True
        return StructuralShape(kind=ShapeKind.OPAQUE)

    if isinstance(value, Mapping):
        if rule.mode is PathMode.IDENTIFIER_MAP:
            state.dynamic_keys_suppressed = bool(value)
            items, item_count, collection_truncated = _bounded_collection(value.values(), total=len(value))
            state.nodes_truncated = state.nodes_truncated or collection_truncated
            return _collection_shape(
                items,
                item_count=item_count,
                kind=ShapeKind.IDENTIFIER_MAP,
                child_path=path + ("[]",),
                policy=policy,
                state=state,
                depth=depth,
                ancestors=next_ancestors,
            )
        if rule.mode not in {PathMode.OBJECT_FIELDS, PathMode.VALUE_MAP}:
            return StructuralShape(kind=ShapeKind.OPAQUE)
        allowed_items = []
        for key in sorted(rule.fields):
            if key in value:
                allowed_items.append((key, value[key]))
        unknown = max(0, len(value) - len(allowed_items))
        fields = tuple(
            ShapeField(
                name=key,
                shape=_extract(
                    child,
                    path=path + (key,),
                    policy=policy,
                    state=state,
                    depth=depth + 1,
                    ancestors=next_ancestors,
                ),
            )
            for key, child in allowed_items
        )
        if unknown:
            state.dynamic_keys_suppressed = True
        return StructuralShape(
            kind=ShapeKind.OBJECT if rule.mode is PathMode.OBJECT_FIELDS else ShapeKind.VALUE_MAP,
            fields=fields,
            unknown_fields=count_bucket(unknown),
        )

    if _is_sequence(value):
        if rule.mode is not PathMode.IDENTIFIER_MAP:
            return StructuralShape(kind=ShapeKind.OPAQUE)
        items, item_count, collection_truncated = _bounded_collection(value, total=len(value))
        state.nodes_truncated = state.nodes_truncated or collection_truncated
        return _collection_shape(
            items,
            item_count=item_count,
            kind=ShapeKind.SEQUENCE,
            child_path=path + ("[]",),
            policy=policy,
            state=state,
            depth=depth,
            ancestors=next_ancestors,
        )

    state.values_suppressed = True
    return StructuralShape(kind=ShapeKind.OPAQUE)


def _collection_shape(
    items: list[Any],
    *,
    item_count: CountBucket,
    kind: ShapeKind,
    child_path: tuple[str, ...],
    policy: Mapping[tuple[str, ...], PathRule],
    state: _ExtractionState,
    depth: int,
    ancestors: frozenset[int],
) -> StructuralShape:
    selected = _select_stratified_items(items, child_path=child_path, policy=policy)
    variants_by_json: dict[str, StructuralShape] = {}
    for item in selected:
        shape = _extract(
            item,
            path=child_path,
            policy=policy,
            state=state,
            depth=depth + 1,
            ancestors=ancestors,
        )
        key = _canonical_model_json(shape)
        variants_by_json.setdefault(key, shape)
    ordered = [variants_by_json[key] for key in sorted(variants_by_json)]
    if len(ordered) > MAX_SHAPE_VARIANTS:
        ordered = ordered[:MAX_SHAPE_VARIANTS]
        state.variants_truncated = True
    return StructuralShape(kind=kind, variants=tuple(ordered), item_count=item_count)


def _bounded_collection(values: Any, *, total: int) -> tuple[list[Any], CountBucket, bool]:
    """Read at most the public collection cap from an already-cached collection."""
    return list(islice(iter(values), MAX_COLLECTION_ITEMS)), count_bucket(total), total > MAX_COLLECTION_ITEMS


def _select_stratified_items(
    items: list[Any],
    *,
    child_path: tuple[str, ...],
    policy: Mapping[tuple[str, ...], PathRule],
) -> list[Any]:
    """Select deterministically across safe structural strata, never raw values."""
    strata: dict[tuple[Any, ...], list[Any]] = {}
    for item in items:
        strata.setdefault(_sampling_key(item, path=child_path, policy=policy), []).append(item)
    selected: list[Any] = []
    ordered_keys = sorted(strata, key=repr)
    offset = 0
    while len(selected) < min(len(items), MAX_COLLECTION_ITEMS):
        added = False
        for key in ordered_keys:
            values = strata[key]
            if offset < len(values):
                selected.append(values[offset])
                added = True
                if len(selected) == MAX_COLLECTION_ITEMS:
                    break
        if not added:
            break
        offset += 1
    return selected


def _sampling_key(
    value: Any,
    *,
    path: tuple[str, ...],
    policy: Mapping[tuple[str, ...], PathRule],
) -> tuple[Any, ...]:
    scalar_type = _scalar_type(value)
    if scalar_type is not None:
        return ("scalar", scalar_type.value)
    adapted = _adapt_object(value)
    if adapted is not None:
        value = adapted
    rule = policy.get(path)
    if isinstance(value, Mapping) and rule is not None:
        allowed = [key for key in sorted(rule.fields) if key in value]
        child_types = tuple(
            (
                key,
                (_scalar_type(value[key]) or ScalarType.UNKNOWN).value,
            )
            for key in allowed
        )
        return ("mapping", rule.mode.value, tuple(allowed), child_types)
    if _is_sequence(value):
        return ("sequence", type(value).__name__)
    return ("opaque", type(value).__module__, type(value).__qualname__)


def _adapt_object(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, BaseModel):
        return {name: getattr(value, name) for name in value.__class__.model_fields}
    return None


def _is_sequence(value: Any) -> bool:
    return isinstance(value, (Sequence, Set)) and not isinstance(value, (str, bytes, bytearray, memoryview))


def _scalar_type(value: Any) -> ScalarType | None:
    if value is None:
        return ScalarType.NULL
    if isinstance(value, Enum):
        return ScalarType.ENUM
    if isinstance(value, bool):
        return ScalarType.BOOLEAN
    if isinstance(value, int):
        return ScalarType.INTEGER
    if isinstance(value, float):
        return ScalarType.FLOAT
    if isinstance(value, str):
        return ScalarType.STRING
    if isinstance(value, (datetime, date)):
        return ScalarType.DATETIME
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ScalarType.UNKNOWN
    return None


def _validate_shape_vocabulary(
    shape: StructuralShape | None,
    vocabulary: Mapping[tuple[str, ...], frozenset[str]],
    *,
    path: tuple[str, ...],
) -> None:
    if shape is None:
        raise ValueError("available resource_shape evidence requires a shape")
    allowed = vocabulary.get(path, frozenset())
    for field in shape.fields:
        if field.name not in allowed:
            raise ValueError("resource_shape contains a field outside its exact vocabulary")
        _validate_shape_vocabulary(field.shape, vocabulary, path=path + (field.name,))
    for variant in shape.variants:
        _validate_shape_vocabulary(variant, vocabulary, path=path + ("[]",))


def validate_support_bundle(value: SupportBundle | Mapping[str, Any]) -> SupportBundle:
    """Validate exact keys, unions, enums, and path-specific string grammars."""
    if isinstance(value, SupportBundle):
        value = value.model_dump(mode="python", round_trip=True)
    return SupportBundle.model_validate(value)


def canonical_json(value: SupportBundle | Mapping[str, Any]) -> str:
    """Return deterministic ASCII JSON after closed-schema validation."""
    payload = validate_support_bundle(value).model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def canonical_shape_json(value: StructuralShape | Mapping[str, Any]) -> str:
    """Serialize an internal structural shape without accepting arbitrary models."""
    if isinstance(value, StructuralShape):
        value = value.model_dump(mode="python", round_trip=True)
    shape = StructuralShape.model_validate(value)
    return json.dumps(shape.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def canonical_response_json(value: SupportBundle | Mapping[str, Any]) -> str:
    """Serialize the exact standard tool response envelope deterministically."""
    bundle = validate_support_bundle(value)
    return json.dumps(
        {"success": True, "data": bundle.model_dump(mode="json")},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def support_bundle_size(value: SupportBundle | Mapping[str, Any]) -> int:
    """Return canonical UTF-8 size of the complete standard response envelope."""
    bundle = validate_support_bundle(value)
    size = len(canonical_response_json(bundle).encode("utf-8"))
    if size > MAX_BUNDLE_BYTES:
        raise ValueError(f"support bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    return size


def bounded_support_bundle(value: SupportBundle | Mapping[str, Any]) -> SupportBundle:
    """Prune whole optional shape nodes deterministically to the envelope cap."""
    bundle = validate_support_bundle(value)
    if len(canonical_response_json(bundle).encode("utf-8")) <= MAX_BUNDLE_BYTES:
        return bundle

    payload = bundle.model_dump(mode="json")
    probe = payload["probe"]
    sanitization = payload["sanitization"]
    sanitization["bytes_truncated"] = True
    sanitization["nodes_truncated"] = True
    shape = probe.get("shape") if isinstance(probe, dict) else None
    variants_removed = False

    while shape is not None and _response_payload_size(payload) > MAX_BUNDLE_BYTES:
        removed_kind = _prune_one_shape_node(shape)
        if removed_kind is None:
            probe["shape"] = None
            probe["status"] = EvidenceStatus.UNAVAILABLE.value
            shape = None
            break
        variants_removed = variants_removed or removed_kind == "variant"

    sanitization["variants_truncated"] = bool(sanitization["variants_truncated"] or variants_removed)
    pruned = validate_support_bundle(payload)
    if len(canonical_response_json(pruned).encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise ValueError("support bundle fixed envelope exceeds byte limit")
    return pruned


def _response_payload_size(payload: Mapping[str, Any]) -> int:
    return len(
        json.dumps(
            {"success": True, "data": payload},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _prune_one_shape_node(shape: dict[str, Any]) -> Literal["field", "variant"] | None:
    variants = shape.get("variants") or []
    if variants:
        variants.pop()
        shape["variants"] = variants
        return "variant"
    for field in reversed(shape.get("fields") or []):
        removed = _prune_one_shape_node(field["shape"])
        if removed is not None:
            return removed
    fields = shape.get("fields") or []
    if fields:
        fields.pop()
        shape["fields"] = fields
        return "field"
    return None


def _canonical_model_json(value: BaseModel) -> str:
    if isinstance(value, StructuralShape):
        return canonical_shape_json(value)
    raise TypeError("only StructuralShape models have an internal canonical form")


def _validated(value: str, pattern: re.Pattern[str], field_name: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not pattern.fullmatch(value):
        raise ValueError(f"{field_name} contains unsupported characters or length")
    return value


def _validated_version(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_VERSION_LENGTH:
        raise ValueError(f"{field_name} exceeds {MAX_VERSION_LENGTH} characters")
    return _validated(value, _VERSION_RE, field_name)


StructuralShape.model_rebuild()
ShapeField.model_rebuild()
