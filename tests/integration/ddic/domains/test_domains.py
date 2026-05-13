from datetime import datetime

import pytest

from connection.connection import call_login
from cts.cts import call_cts_transport_create, call_cts_transport_delete
from ddic.domains.domains import (
    DdicDomainFixValue,
    DdicDomainUpdateRequest,
    call_ddic_domain_create,
    call_ddic_domain_lock,
    call_ddic_domain_read,
    call_ddic_domain_unlock,
    call_ddic_domain_update,
)
from deletion.deletion import call_deletion_delete
from packages.packages import PackageCreateRequest, call_package_create, call_package_delete


def _unique_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


def _delete_domain(system_id: str, name: str, transport_number: str = "") -> None:
    call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
        transportNumber=transport_number,
    )


def _update_domain(system_id: str, name: str, request: DdicDomainUpdateRequest, transport_number: str = ""):
    lock_response = call_ddic_domain_lock(system_id, name)
    assert lock_response.result is True
    assert lock_response.data is not None
    try:
        update_response = call_ddic_domain_update(
            systemId=system_id,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transport_number,
        )
    finally:
        call_ddic_domain_unlock(system_id, name, lock_response.data.lockHandle)
    return update_response


@pytest.fixture
def ddic_transport_package(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    transport_response = call_cts_transport_create(
        systemId=system_id,
        packageName="$TMP",
        requestText="Pytest DDIC Domains",
        objectUri="/sap/bc/adt/oo/classes/YCDX_CL_120226",
        operation="I",
    )
    assert transport_response.result is True
    assert transport_response.data is not None
    transport_number = transport_response.data.transportNumber

    package_name = _unique_name("ZCDX")
    package_response = call_package_create(
        systemId=system_id,
        corrNr=transport_number,
        request=PackageCreateRequest(
            name=package_name,
            description="Pytest DDIC package",
            language="EN",
            responsible="DEVELOPER",
            softwareComponent="HOME",
        ),
    )
    assert package_response.result is True

    try:
        yield system_id, package_name, transport_number
    finally:
        call_package_delete(system_id, package_name, transport_number)
        call_cts_transport_delete(system_id, transport_number)


@pytest.mark.integration
def test_ddic_domain_tmp_char_without_fixed_values(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXCH")

    try:
        create_response = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest local CHAR",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="CHAR",
                length=12,
                outputLength=12,
                lowercase=True,
            ),
        )
        assert update_response.result is True

        read_response = call_ddic_domain_read(system_id, domain_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.dataType == "CHAR"
        assert read_response.data.length == 12
        assert read_response.data.fixValues == []
        assert read_response.data.lowercase is True
        assert read_response.data.packageName == "$TMP"
    finally:
        _delete_domain(system_id, domain_name)


@pytest.mark.integration
def test_ddic_domain_tmp_numc_with_alpha(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXNM")

    try:
        create_response = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest NUMC ALPHA",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="NUMC",
                length=10,
                outputLength=10,
                conversionExit="ALPHA",
            ),
        )
        assert update_response.result is True

        read_response = call_ddic_domain_read(system_id, domain_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.dataType == "NUMC"
        assert read_response.data.conversionExit == "ALPHA"
    finally:
        _delete_domain(system_id, domain_name)


@pytest.mark.integration
def test_ddic_domain_tmp_with_fixed_values(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXFV")

    try:
        create_response = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest fix values",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="CHAR",
                length=1,
                outputLength=1,
                fixValues=[
                    DdicDomainFixValue(low="A", text="Activo"),
                    DdicDomainFixValue(low="I", text="Inactivo"),
                ],
            ),
        )
        assert update_response.result is True

        read_response = call_ddic_domain_read(system_id, domain_name)
        assert read_response.result is True
        assert read_response.data is not None
        lows = {item["low"]: item["text"] for item in read_response.data.fixValues}
        assert lows["A"] == "Activo"
        assert lows["I"] == "Inactivo"
    finally:
        _delete_domain(system_id, domain_name)


@pytest.mark.integration
def test_ddic_domain_tmp_char_case_sensitive(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXCS")

    try:
        create_response = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest case sensitive CHAR",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="CHAR",
                length=8,
                outputLength=8,
                lowercase=False,
            ),
        )
        assert update_response.result is True

        read_response = call_ddic_domain_read(system_id, domain_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.dataType == "CHAR"
        assert read_response.data.lowercase is False
    finally:
        _delete_domain(system_id, domain_name)


@pytest.mark.integration
def test_ddic_domain_transport_package_decimal(ddic_transport_package):
    system_id, package_name, transport_number = ddic_transport_package
    domain_name = _unique_name("ZCDXDM")

    try:
        create_response = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest transport DEC",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="DEC",
                length=13,
                decimals=2,
                outputLength=16,
                signExists=True,
            ),
            transport_number,
        )
        assert update_response.result is True

        read_response = call_ddic_domain_read(system_id, domain_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.packageName == package_name
        assert read_response.data.dataType == "DEC"
        assert read_response.data.decimals == 2
        assert read_response.data.signExists is True
    finally:
        _delete_domain(system_id, domain_name, transport_number)


@pytest.mark.integration
def test_ddic_domain_delete_removes_object(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXDL")

    create_response = call_ddic_domain_create(
        systemId=system_id,
        name=domain_name,
        description="Pytest delete domain",
        packageName="$TMP",
        language="EN",
        responsible="DEVELOPER",
    )
    assert create_response.result is True

    delete_response = call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/domains/{domain_name.lower()}",
        transportNumber="",
    )
    assert delete_response.result is True

    read_response = call_ddic_domain_read(system_id, domain_name)
    assert read_response.result is False
