import pytest

import configuration


def test_load_system_configs_allows_empty_environment(monkeypatch):
    monkeypatch.delenv("SAP_SYSTEMS_JSON", raising=False)
    monkeypatch.delenv("SAP_SERVER", raising=False)
    monkeypatch.delenv("SAP_USER", raising=False)
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    monkeypatch.delenv("SAP_CLIENT", raising=False)

    assert configuration._load_system_configs() == {}


def test_get_system_config_explains_empty_configuration(monkeypatch):
    monkeypatch.setattr(configuration, "SYSTEM_CONFIGS", {})

    with pytest.raises(KeyError, match="Add a system through the dashboard"):
        configuration.get_system_config("DEV")
