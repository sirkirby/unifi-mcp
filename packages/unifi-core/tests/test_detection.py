from unifi_core.detection import ControllerType


class TestControllerType:
    def test_enum_values(self):
        assert ControllerType.UNIFI_OS.value == "proxy"
        assert ControllerType.STANDALONE.value == "direct"
        assert ControllerType.AUTO.value == "auto"

    def test_from_config_proxy(self):
        assert ControllerType.from_config("proxy") == ControllerType.UNIFI_OS

    def test_from_config_direct(self):
        assert ControllerType.from_config("direct") == ControllerType.STANDALONE

    def test_from_config_auto(self):
        assert ControllerType.from_config("auto") == ControllerType.AUTO

    def test_from_config_case_insensitive(self):
        assert ControllerType.from_config("PROXY") == ControllerType.UNIFI_OS
        assert ControllerType.from_config("Direct") == ControllerType.STANDALONE
        assert ControllerType.from_config("AUTO") == ControllerType.AUTO

    def test_from_config_unknown_falls_back_to_auto(self):
        assert ControllerType.from_config("unknown") == ControllerType.AUTO
        assert ControllerType.from_config("") == ControllerType.AUTO

    def test_enum_members_complete(self):
        members = set(ControllerType)
        assert members == {ControllerType.UNIFI_OS, ControllerType.STANDALONE, ControllerType.AUTO}
