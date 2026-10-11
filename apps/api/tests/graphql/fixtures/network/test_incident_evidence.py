"""Fixture proof that the Network incident evidence field returns the document as JSON.

# tool: unifi_get_incident_evidence
"""

from unittest.mock import patch

import pytest
from unifi_api.graphql.type_registry_init import build_type_registry

from tests.graphql.fixtures._helpers import bootstrap, graphql_query
from tests.unit._incident_evidence_support import NOW, REQUEST, FrozenDatetime, network_scenario


@pytest.mark.asyncio
async def test_incident_evidence_resolver_returns_the_document(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")

    async def get_event_reader(session, controller_id, product, *, site=None):
        assert (product, site) == ("network", "default")
        return network_scenario("healthy_empty")

    app.state.manager_factory.get_event_reader = get_event_reader
    with (
        patch("unifi_core.incident_collection.datetime", FrozenDatetime),
        patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()),
    ):
        body = await graphql_query(
            app,
            key,
            f'{{ network {{ incidentEvidence(controller: "{cid}", start: "{REQUEST["start"]}", '
            f'end: "{REQUEST["end"]}") {{ document }} }} }}',
        )
    assert "errors" not in body
    document = body["data"]["network"]["incidentEvidence"]["document"]
    assert document["sources"][0]["outcome"] == "empty"
    assert build_type_registry().lookup_tool("unifi_get_incident_evidence") is not None
