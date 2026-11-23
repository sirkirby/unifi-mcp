"""Traffic-flow filters and fields on the REST route and the GraphQL resolver."""

from types import SimpleNamespace

import pytest
from aiounifi.errors import AiounifiException
from httpx import ASGITransport, AsyncClient
from tests.graphql.fixtures._helpers import bootstrap, graphql_query, stub_managers
from unifi_api.services.managers import ManagerFactory

NOW_MS = 1795330583185
THREE_GB = 3_221_225_472

# Shape recorded from POST /traffic-flows on Network 11.0; values are synthetic.
FLOW = {
    "id": "flow-ips",
    "action": "allowed",
    "risk": "medium",
    "time": NOW_MS,
    "flow_start_time": NOW_MS - 1,
    "flow_end_time": NOW_MS - 2,
    "bytes_total": THREE_GB,
    "bytes_rx": THREE_GB + 1,
    "bytes_tx": THREE_GB + 2,
    "source": {"ip": "192.0.2.10", "region": "DE"},
    "destination": {"ip": "198.51.100.20", "region": "NL"},
    "policies": [
        {
            "id": "policy-1",
            "type": "INTRUSION_PREVENTION",
            "internal_type": "SIGNATURE",
            "name": "Example signature",
            "ips_category": "EMERGING_SCAN",
        },
        {"type": "FIREWALL", "internal_type": "CONNTRACK"},
    ],
}

# (REST parameter, GraphQL argument, query field, values)
FILTERS = [
    ("risk", "risk", "risk", ["medium", "high"]),
    ("action", "action", "action", ["blocked", "allowed"]),
    ("direction", "direction", "direction", ["outgoing", "local"]),
    ("protocol", "protocol", "protocol", ["TCP", "UDP"]),
    ("service", "service", "service", ["DNS", "HTTPS"]),
    ("source_mac", "sourceMac", "source_mac", ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]),
    ("source_ip", "sourceIp", "source_ip", ["192.0.2.10", "192.0.2.11"]),
    ("source_network_id", "sourceNetworkId", "source_network_id", ["net-a", "net-b"]),
    ("source_port", "sourcePort", "source_port", [0, 65535]),
    ("destination_domain", "destinationDomain", "destination_domain", ["a.example", "b.example"]),
    ("destination_ip", "destinationIp", "destination_ip", ["198.51.100.20", "198.51.100.21"]),
    ("destination_port", "destinationPort", "destination_port", [22, 443]),
    ("destination_region", "destinationRegion", "destination_region", ["NL", "DE"]),
]


@pytest.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(monkeypatch, {})
    queries = []
    state = SimpleNamespace(app=app, key=key, cid=cid, queries=queries, error=None, truncated=False)

    async def get_traffic_flows(query):
        if state.error:
            raise state.error
        queries.append(query)
        return {"flows": [FLOW], "has_next": False, "truncated": state.truncated}

    async def get_manager(self, *args, **kwargs):
        return SimpleNamespace(get_traffic_flows=get_traffic_flows)

    monkeypatch.setattr(ManagerFactory, "get_domain_manager", get_manager)
    return state


async def _get(api, params):
    async with AsyncClient(transport=ASGITransport(app=api.app), base_url="http://test") as client:
        return await client.get(
            "/v1/sites/default/traffic-flows",
            params=[("controller", api.cid), *params],
            headers={"Authorization": f"Bearer {api.key}"},
        )


def _literal(value):
    return str(value) if isinstance(value, int) else f'"{value}"'


@pytest.mark.asyncio
@pytest.mark.parametrize("param,argument,field,values", FILTERS)
async def test_rest_filter_reaches_the_query(api, param, argument, field, values):
    response = await _get(api, [(param, value) for value in values])
    assert response.status_code == 200, response.text
    [query] = api.queries
    assert getattr(query, field) == values
    assert [getattr(query, other[2]) for other in FILTERS if other[2] != field] == [None] * (len(FILTERS) - 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("param,argument,field,values", FILTERS)
async def test_graphql_filter_reaches_the_query(api, param, argument, field, values):
    body = await graphql_query(
        api.app,
        api.key,
        f'{{ network {{ trafficFlows(controller: "{api.cid}", {argument}: [{", ".join(map(_literal, values))}]) '
        "{ items { id } } } }",
    )
    assert body.get("errors") is None, body
    [query] = api.queries
    assert getattr(query, field) == values
    assert [getattr(query, other[2]) for other in FILTERS if other[2] != field] == [None] * (len(FILTERS) - 1)


@pytest.mark.asyncio
async def test_single_value_and_no_filters(api):
    assert (await _get(api, [("risk", "medium")])).status_code == 200
    assert (await _get(api, [])).status_code == 200
    filtered, plain = api.queries
    assert filtered.risk == ["medium"]
    assert [getattr(plain, entry[2]) for entry in FILTERS] == [None] * len(FILTERS)


@pytest.mark.asyncio
@pytest.mark.parametrize("param", ["source_port", "destination_port"])
@pytest.mark.parametrize("value", ["-1", "65536", "ssh"])
async def test_rest_rejects_an_invalid_port(api, param, value):
    assert (await _get(api, [(param, value)])).status_code == 422
    assert api.queries == []


@pytest.mark.asyncio
async def test_rest_returns_regions_and_policies(api):
    response = await _get(api, [])
    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    assert (item["source"]["region"], item["destination"]["region"]) == ("DE", "NL")
    assert item["policies"] == [
        {
            "id": "policy-1",
            "type": "INTRUSION_PREVENTION",
            "internal_type": "SIGNATURE",
            "name": "Example signature",
            "ips_category": "EMERGING_SCAN",
        },
        {"id": None, "type": "FIREWALL", "internal_type": "CONNTRACK", "name": None, "ips_category": None},
    ]


@pytest.mark.asyncio
async def test_graphql_returns_regions_policies_and_64_bit_values(api):
    body = await graphql_query(
        api.app,
        api.key,
        f"""{{ network {{ trafficFlows(controller: "{api.cid}", timeFrom: {NOW_MS - 1000}, timeTo: {NOW_MS}) {{
            items {{
                time flowStartTime flowEndTime bytesTotal bytesRx bytesTx
                source {{ region }} destination {{ region }}
                policies {{ id type internalType name ipsCategory }}
            }}
        }} }} }}""",
    )
    assert body.get("errors") is None, body
    [query] = api.queries
    assert (query.time_from, query.time_to) == (NOW_MS - 1000, NOW_MS)
    assert body["data"]["network"]["trafficFlows"]["items"] == [
        {
            "time": NOW_MS,
            "flowStartTime": NOW_MS - 1,
            "flowEndTime": NOW_MS - 2,
            "bytesTotal": THREE_GB,
            "bytesRx": THREE_GB + 1,
            "bytesTx": THREE_GB + 2,
            "source": {"region": "DE"},
            "destination": {"region": "NL"},
            "policies": [
                {
                    "id": "policy-1",
                    "type": "INTRUSION_PREVENTION",
                    "internalType": "SIGNATURE",
                    "name": "Example signature",
                    "ipsCategory": "EMERGING_SCAN",
                },
                {"id": None, "type": "FIREWALL", "internalType": "CONNTRACK", "name": None, "ipsCategory": None},
            ],
        }
    ]


def test_policies_tolerate_firmware_variation():
    from unifi_api.graphql.types.network.traffic_flow import TrafficFlow

    assert TrafficFlow.from_manager_output({}).to_dict()["policies"] == []
    odd = TrafficFlow.from_manager_output({"policies": [{"type": 5, "name": {"nested": True}}]})
    assert odd.to_dict()["policies"] == [
        {"id": None, "type": None, "internal_type": None, "name": None, "ips_category": None}
    ]


@pytest.mark.asyncio
async def test_statistics_application_bytes_are_64_bit(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await bootstrap(tmp_path, product="network")
    stub_managers(
        monkeypatch,
        {
            ("network", "traffic_flow_manager", "get_traffic_flow_statistics"): {
                "top_applications": [{"application_id": 1, "category_id": 2, "bytes": THREE_GB}]
            }
        },
    )
    body = await graphql_query(
        app, key, f'{{ network {{ trafficFlowStatistics(controller: "{cid}") {{ topApplications {{ bytes }} }} }} }}'
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["trafficFlowStatistics"]["topApplications"] == [{"bytes": THREE_GB}]


async def _gql(api, args, variables=""):
    query = f'{{ network {{ trafficFlows(controller: "{api.cid}", {args}) {{ items {{ id }} }} }} }}'
    return await graphql_query(api.app, api.key, variables + query)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "   "])
async def test_rest_refuses_a_blank_filter(api, value):
    response = await _get(api, [("destination_region", value)])
    assert response.status_code == 422
    assert "destination_region" in response.text
    assert api.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args,named",
    [("risk: []", "risk"), ('destinationRegion: [" "]', "destination_region"), ("sourcePort: [70000]", "source_port")],
)
async def test_graphql_refuses_a_bad_filter_by_name_only(api, args, named):
    body = await _gql(api, args)
    [error] = body["errors"]
    assert error["message"] == f"invalid traffic-flow filter: {named}"
    assert error["extensions"]["code"] == "BAD_REQUEST"
    assert api.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["true", '"abc"', "1.5", str(2**63)])
async def test_graphql_times_take_only_64_bit_integers(api, value):
    body = await _gql(api, f"timeFrom: {value}, timeTo: {NOW_MS}")
    assert body.get("errors"), body
    assert api.queries == []


@pytest.mark.asyncio
async def test_controller_rejection_is_a_client_error(api):
    api.error = AiounifiException({"errorCode": 400, "message": "private controller text"})
    response = await _get(api, [("risk", "suspicious")])
    assert response.status_code == 400
    assert "the controller rejected the traffic-flow query" in response.text
    assert "private controller text" not in response.text
    body = await _gql(api, 'risk: ["suspicious"]')
    [error] = body["errors"]
    assert error["message"] == "the controller rejected the traffic-flow query"
    assert error["extensions"]["code"] == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_a_rejection_folded_into_the_message_is_still_a_client_error(api):
    # aiounifi folds the status of the errors it maps into the message instead of the decoded body.
    api.error = AiounifiException("Call https://controller/v2/api/traffic-flows received 400 Bad Request")
    response = await _get(api, [("risk", "suspicious")])
    assert response.status_code == 400
    assert "controller/v2" not in response.text


@pytest.mark.asyncio
async def test_graphql_time_window_errors_are_client_errors(api):
    body = await _gql(api, f"timeFrom: {NOW_MS}")
    [error] = body["errors"]
    assert error["extensions"]["code"] == "BAD_REQUEST"
    assert api.queries == []


@pytest.mark.asyncio
async def test_other_controller_failures_are_not_blamed_on_the_filter(api):
    api.error = AiounifiException({"errorCode": 500, "message": "broken"})
    body = await _gql(api, 'risk: ["medium"]')
    [error] = body["errors"]
    assert "rejected" not in error["message"]


@pytest.mark.asyncio
async def test_client_name_filter_is_not_offered(api):
    body = await _gql(api, 'sourceName: ["client-a"]')
    assert body.get("errors"), body
    assert api.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize("param", ["source_name", "source_host", "destination_regions", "Risk"])
async def test_rest_refuses_an_unknown_parameter_instead_of_returning_everything(api, param):
    response = await _get(api, [(param, "x")])
    assert response.status_code == 422
    assert param in response.text
    assert api.queries == []


@pytest.mark.asyncio
async def test_rest_accepts_every_other_declared_parameter(api):
    params = [("search_text", "x"), ("page_size", "5"), ("time_from", str(NOW_MS - 9)), ("time_to", str(NOW_MS))]
    assert (await _get(api, params)).status_code == 200
    assert (await _get(api, [("within_hours", "2"), ("cursor", "MQ==")])).status_code == 200
    assert len(api.queries) == 2


@pytest.mark.asyncio
async def test_rest_does_not_blame_the_query_for_a_controller_outage(api):
    api.error = AiounifiException({"errorCode": 500, "message": "broken"})
    async with AsyncClient(
        transport=ASGITransport(app=api.app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/v1/sites/default/traffic-flows?controller={api.cid}", headers={"Authorization": f"Bearer {api.key}"}
        )
    assert response.status_code >= 500
    assert "rejected" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("truncated", [True, False])
async def test_rest_says_when_the_controller_stopped_early(api, truncated):
    api.truncated = truncated
    response = await _get(api, [])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["truncated"] is truncated
    assert body["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("truncated", [True, False])
async def test_graphql_says_when_the_controller_stopped_early(api, truncated):
    api.truncated = truncated
    body = await graphql_query(
        api.app, api.key, f'{{ network {{ trafficFlows(controller: "{api.cid}") {{ truncated nextCursor }} }} }}'
    )
    assert body.get("errors") is None, body
    assert body["data"]["network"]["trafficFlows"] == {"truncated": truncated, "nextCursor": None}


@pytest.mark.asyncio
async def test_openapi_declares_truncated(api):
    schema = api.app.openapi()
    ref = schema["paths"]["/v1/sites/{site_id}/traffic-flows"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    page = schema["components"]["schemas"][ref.rsplit("/", 1)[1]]
    assert page["properties"]["truncated"]["type"] == "boolean"
    assert "truncated" in page["required"]
