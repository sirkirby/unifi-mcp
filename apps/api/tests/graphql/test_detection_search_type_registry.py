"""Type-registry coverage for the detection-search read tools.

``protect_search_detections`` and ``protect_detection_search_labels`` are
read tools, so their projection is a Strawberry type registered in the
type registry (mirroring ``protect_list_known_license_plates``). Without the
registration the CI ``validate_manifest`` gate in
``test_serializer_coverage`` would reject the manifest.
"""

from unifi_api.graphql.type_registry_init import build_type_registry


def test_search_detections_registered_as_read_tool() -> None:
    reg = build_type_registry()
    assert "protect_search_detections" in set(reg.all_tools())


def test_detection_search_labels_registered_as_read_tool() -> None:
    reg = build_type_registry()
    assert "protect_detection_search_labels" in set(reg.all_tools())
