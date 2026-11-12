"""Account inputs never accept console configuration or echo rejected secrets."""

import pytest
from pydantic import SecretStr, ValidationError
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate, SiteManagerConnectionPatch

KEY = "synthetic-cloud-key-DO-NOT-DISCLOSE-42"


def test_create_and_omitted_patch():
    value = SiteManagerConnectionCreate(name="  Test account  ", site_manager_api_key=KEY)
    assert value.name == "Test account"
    assert isinstance(value.site_manager_api_key, SecretStr)
    assert KEY not in repr(value)
    assert KEY[:8] not in repr(value) and KEY[-8:] not in repr(value)
    assert SiteManagerConnectionPatch().model_fields_set == set()


@pytest.mark.parametrize("model", [SiteManagerConnectionCreate, SiteManagerConnectionPatch])
@pytest.mark.parametrize(
    "field,value",
    [
        ("site_manager_api_key", None),
        ("site_manager_api_key", " "),
        ("site_manager_api_key", 12),
        ("site_manager_api_key", {"rejected-secret-marker": KEY}),
        ("site_manager_api_key", [KEY]),
        ("name", None),
        ("name", " "),
        ("name", "a" * 129),
        ("name", 12),
        ("base_url", KEY),
        ("api_token", KEY),
        ("username", KEY),
        ("product_kinds", ["sitemanager"]),
    ],
)
def test_invalid_inputs_are_value_free(model, field, value):
    data = {"name": "Test", "site_manager_api_key": KEY, field: value}
    with pytest.raises(ValidationError) as error:
        model.model_validate(data)
    assert KEY not in str(error.value)
    assert KEY[:8] not in str(error.value) and KEY[-8:] not in str(error.value)
