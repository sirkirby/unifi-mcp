from unifi_core.connection import ConnectionConfig


class TestConnectionConfig:
    def test_defaults(self):
        cfg = ConnectionConfig(host="192.0.2.1")
        assert cfg.host == "192.0.2.1"
        assert cfg.port == 443
        assert cfg.verify_ssl is False
        assert cfg.timeout == 30.0

    def test_custom_values(self):
        cfg = ConnectionConfig(host="10.0.0.1", port=8443, verify_ssl=True, timeout=60.0)
        assert cfg.host == "10.0.0.1"
        assert cfg.port == 8443
        assert cfg.verify_ssl is True
        assert cfg.timeout == 60.0

    def test_url_base(self):
        cfg = ConnectionConfig(host="192.0.2.1")
        assert cfg.url_base == "https://192.0.2.1:443"

    def test_url_base_custom_port(self):
        cfg = ConnectionConfig(host="10.0.0.1", port=8443)
        assert cfg.url_base == "https://10.0.0.1:8443"

    def test_ssl_context_when_verify_false(self):
        cfg = ConnectionConfig(host="192.0.2.1", verify_ssl=False)
        assert cfg.ssl_context is False

    def test_ssl_context_when_verify_true(self):
        cfg = ConnectionConfig(host="192.0.2.1", verify_ssl=True)
        assert cfg.ssl_context is None
