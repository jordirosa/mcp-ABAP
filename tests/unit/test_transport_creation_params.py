from types import SimpleNamespace

import pytest

from ddic.dataelements import dataelements
from ddic.ddl import ddl
from ddic.domains import domains
from ddic.tables import tables
from packages import packages
from source.classes import classes
from source.functions import groups
from source.interfaces import interfaces
from source.programs import includes, programs


SYSTEM_CONFIG = SimpleNamespace(
    server="https://fake",
    id="A4H",
    language="EN",
    user="DEVELOPER",
)


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return SimpleNamespace(
            status_code=400,
            reason="Bad Request",
            text="Expected test rejection",
            headers={},
        )


CASES = [
    (
        domains,
        lambda transport: domains.call_ddic_domain_create(
            "A4H",
            name="ZTEST_DOMAIN",
            description="Test",
            packageName="ZTEST",
            transportNumber=transport,
        ),
    ),
    (
        dataelements,
        lambda transport: dataelements.call_ddic_dataelement_create(
            "A4H",
            name="ZTEST_ELEMENT",
            description="Test",
            packageName="ZTEST",
            transportNumber=transport,
        ),
    ),
    (
        tables,
        lambda transport: tables.call_ddic_table_create(
            "A4H",
            name="ZTEST_TABLE",
            description="Test",
            packageName="ZTEST",
            transportNumber=transport,
        ),
    ),
    (
        programs,
        lambda transport: programs.call_program_create(
            "A4H",
            programs.ProgramCreateRequest(name="ZTEST_PROGRAM", description="Test", packageName="ZTEST"),
            transport,
        ),
    ),
    (
        includes,
        lambda transport: includes.call_include_create(
            "A4H",
            includes.IncludeCreateRequest(name="ZTEST_INCLUDE", description="Test", packageName="ZTEST"),
            transport,
        ),
    ),
    (
        classes,
        lambda transport: classes.call_class_create(
            "A4H",
            classes.ClassCreateRequest(name="ZCL_TEST", description="Test", packageName="ZTEST"),
            transport,
        ),
    ),
    (
        interfaces,
        lambda transport: interfaces.call_interface_create(
            "A4H",
            interfaces.InterfaceCreateRequest(name="ZIF_TEST", description="Test", packageName="ZTEST"),
            transport,
        ),
    ),
    (
        groups,
        lambda transport: groups.call_function_group_create(
            "A4H",
            groups.FunctionGroupCreateRequest(name="ZTEST_GROUP", description="Test", packageName="ZTEST"),
            transport,
        ),
    ),
    (
        ddl,
        lambda transport: ddl.call_ddic_ddl_source_create(
            "A4H",
            name="ZTEST_DDL",
            description="Test",
            packageName="ZTEST",
            transportNumber=transport,
        ),
    ),
    (
        packages,
        lambda transport: packages.call_package_create(
            "A4H",
            packages.PackageCreateRequest(name="ZTEST_PACKAGE", description="Test"),
            transport,
        ),
    ),
]


@pytest.mark.parametrize(("module", "call_create"), CASES)
def test_creation_sends_transport_as_corrnr_query_param(monkeypatch, module, call_create):
    session = FakeSession()
    monkeypatch.setattr(module, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(module, "get_system_config", lambda system_id: SYSTEM_CONFIG)
    monkeypatch.setattr(module, "get_session", lambda system_id: session)

    call_create("A4HK900123")

    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert "corrNr" not in url
    assert kwargs["params"] == {"corrNr": "A4HK900123"}
    assert "X-sap-adt-corrnr" not in kwargs["headers"]


@pytest.mark.parametrize(("module", "call_create"), CASES)
def test_creation_omits_corrnr_when_transport_is_empty(monkeypatch, module, call_create):
    session = FakeSession()
    monkeypatch.setattr(module, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(module, "get_system_config", lambda system_id: SYSTEM_CONFIG)
    monkeypatch.setattr(module, "get_session", lambda system_id: session)

    call_create("   ")

    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert "corrNr" not in url
    assert kwargs["params"] == {}
    assert "X-sap-adt-corrnr" not in kwargs["headers"]
