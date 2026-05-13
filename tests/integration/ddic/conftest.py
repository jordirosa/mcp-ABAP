from datetime import datetime

import pytest

from connection.connection import call_login
from cts.cts import call_cts_transport_create, call_cts_transport_delete
from packages.packages import PackageCreateRequest, call_package_create, call_package_delete


def unique_ddic_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


@pytest.fixture
def ddic_transport_package(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    transport_response = call_cts_transport_create(
        systemId=system_id,
        packageName="$TMP",
        requestText="Pytest DDIC",
        objectUri="/sap/bc/adt/oo/classes/YCDX_CL_120226",
        operation="I",
    )
    assert transport_response.result is True
    assert transport_response.data is not None
    transport_number = transport_response.data.transportNumber

    package_name = unique_ddic_name("ZCDX")
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
