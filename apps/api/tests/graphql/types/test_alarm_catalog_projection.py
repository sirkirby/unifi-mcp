"""AlarmCatalog projection: dict, pydantic and fallback inputs."""

from unifi_api.graphql.types.protect.alarms import AlarmCatalog
from unifi_core.protect.models.alarm_rules import AlarmCatalog as CoreAlarmCatalog
from unifi_core.protect.models.alarm_rules import AlarmCatalogTrigger


def test_dict_passes_through():
    inst = AlarmCatalog.from_manager_output({"triggers": [{"trigger_id": "t"}], "actions": [], "scope": {}})
    assert inst.triggers == [{"trigger_id": "t"}]
    assert inst.to_dict() == {"triggers": [{"trigger_id": "t"}], "actions": [], "scope": {}}


def test_pydantic_model_is_dumped():
    model = CoreAlarmCatalog(triggers=[AlarmCatalogTrigger(trigger_id="t", title="T")])
    inst = AlarmCatalog.from_manager_output(model)
    assert [t["trigger_id"] for t in inst.triggers] == ["t"]
    assert inst.to_dict()["actions"] == []


def test_unexpected_value_falls_back_to_string():
    inst = AlarmCatalog.from_manager_output(42)
    assert (inst.triggers, inst.actions, inst.scope) == (None, None, None)
    assert inst.to_dict() == {"result": "42"}


def test_empty_instance_is_empty_dict():
    assert AlarmCatalog(triggers=None, actions=None, scope=None).to_dict() == {}
