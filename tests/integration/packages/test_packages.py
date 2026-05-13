from datetime import datetime

import pytest

from connection.connection import call_login
from cts.cts import call_cts_transport_create, call_cts_transport_delete
from packages.packages import PackageCreateRequest, call_package_create, call_package_delete, call_package_read


def _unique_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


@pytest.fixture
def package_transport(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    transport_response = call_cts_transport_create(
        systemId=system_id,
        packageName="$TMP",
        requestText="Pytest packages",
        objectUri="/sap/bc/adt/oo/classes/YCDX_CL_120226",
        operation="I",
    )
    assert transport_response.result is True
    assert transport_response.data is not None

    try:
        yield system_id, transport_response.data.transportNumber
    finally:
        call_cts_transport_delete(system_id, transport_response.data.transportNumber)


@pytest.mark.integration
def test_package_create_read_delete(package_transport):
    system_id, transport_number = package_transport
    package_name = _unique_name("ZCDX")

    create_response = call_package_create(
        systemId=system_id,
        corrNr=transport_number,
        request=PackageCreateRequest(
            name=package_name,
            description="Pytest package",
            language="EN",
            responsible="DEVELOPER",
            softwareComponent="HOME",
        ),
    )
    assert create_response.result is True
    assert create_response.data is not None
    assert create_response.data.name == package_name

    read_response = call_package_read(system_id, package_name)
    assert read_response.result is True
    assert read_response.data is not None
    assert read_response.data.name == package_name
    assert read_response.data.description == "Pytest package"
    assert read_response.data.packageType == "development"
    assert read_response.data.softwareComponent == "HOME"

    delete_response = call_package_delete(system_id, package_name, transport_number)
    assert delete_response.result is True
    assert delete_response.data is not None
    assert delete_response.data.isDeleted is True

    read_after_delete = call_package_read(system_id, package_name)
    assert read_after_delete.result is False


@pytest.mark.integration
def test_package_create_subpackage_reads_superpackage(package_transport):
    system_id, transport_number = package_transport
    parent_name = _unique_name("ZCPA")
    child_name = _unique_name("ZCCH")

    try:
        parent_response = call_package_create(
            systemId=system_id,
            corrNr=transport_number,
            request=PackageCreateRequest(
                name=parent_name,
                description="Pytest parent package",
                language="EN",
                responsible="DEVELOPER",
                softwareComponent="HOME",
            ),
        )
        assert parent_response.result is True

        child_response = call_package_create(
            systemId=system_id,
            corrNr=transport_number,
            request=PackageCreateRequest(
                name=child_name,
                description="Pytest child package",
                language="EN",
                responsible="DEVELOPER",
                superPackageName=parent_name,
                softwareComponent="HOME",
            ),
        )
        assert child_response.result is True
        assert child_response.data is not None

        read_child = call_package_read(system_id, child_name)
        assert read_child.result is True
        assert read_child.data is not None
        assert read_child.data.name == child_name
        assert read_child.data.superPackageName == parent_name
    finally:
        call_package_delete(system_id, child_name, transport_number)
        call_package_delete(system_id, parent_name, transport_number)
