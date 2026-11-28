"""The traffic-flow manager gets the client list it resolves names through."""


def test_runtime_traffic_flow_manager_has_the_client_manager(monkeypatch):
    from unifi_network_mcp import runtime

    connection, dpi, clients = object(), object(), object()
    monkeypatch.setattr(runtime, "get_connection_manager", lambda: connection)
    monkeypatch.setattr(runtime, "get_dpi_manager", lambda: dpi)
    monkeypatch.setattr(runtime, "get_client_manager", lambda: clients)
    runtime.get_traffic_flow_manager.cache_clear()
    try:
        manager = runtime.get_traffic_flow_manager()
        assert manager._connection is connection
        assert manager._dpi_manager is dpi
        assert manager._client_manager is clients
    finally:
        runtime.get_traffic_flow_manager.cache_clear()
