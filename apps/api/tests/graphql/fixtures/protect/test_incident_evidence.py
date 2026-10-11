"""Fixture proof that the Protect incident evidence field returns the document as JSON.

# tool: protect_get_incident_evidence
"""

from unittest.mock import patch

import pytest

from tests.graphql.fixtures._helpers import bootstrap, graphql_query
from tests.unit._incident_evidence_support import REQUEST, FrozenDatetime, protect_scenario


@pytest.mark.asyncio
async def test_incident_evidence_resolver_returns_the_document(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="protect")

    async def get_event_reader(session, controller_id, product, *, site=None):
        assert (product, site) == ("protect", None)
        return protect_scenario("healthy_empty")

    app.state.manager_factory.get_event_reader = get_event_reader
    with patch("unifi_core.incident_collection.datetime", FrozenDatetime):
        body = await graphql_query(
            app,
            key,
            f'{{ protect {{ incidentEvidence(controller: "{cid}", start: "{REQUEST["start"]}", '
            f'end: "{REQUEST["end"]}") {{ document }} }} }}',
        )
    assert "errors" not in body
    document = body["data"]["protect"]["incidentEvidence"]["document"]
    assert document["sources"][0]["outcome"] == "empty"
