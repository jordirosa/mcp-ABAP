import pytest

from connection.connection import call_login
from cts.cts import (
    call_cts_transport_create,
    call_cts_transport_delete,
    call_cts_transport_read,
    call_cts_transport_read_to_file,
    call_cts_transport_write_from_file,
)


@pytest.fixture
def cts_transport(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    create_response = call_cts_transport_create(
        systemId=system_id,
        packageName="$TMP",
        requestText="Pytest CTS",
        objectUri="/sap/bc/adt/oo/classes/YCDX_CL_120226",
        operation="I",
    )
    assert create_response.result is True
    assert create_response.data is not None
    transport_number = create_response.data.transportNumber

    try:
        yield system_id, transport_number
    finally:
        call_cts_transport_delete(system_id, transport_number)


@pytest.mark.integration
def test_cts_transport_create_and_read(cts_transport):
    system_id, transport_number = cts_transport

    read_response = call_cts_transport_read(system_id, transport_number)

    assert read_response.result is True
    assert read_response.data is not None
    assert read_response.data.transportNumber == transport_number
    assert read_response.data.description == "Pytest CTS"
    assert read_response.data.tasks


@pytest.mark.integration
def test_cts_transport_read_to_file_and_write_from_file(cts_transport, tmp_path):
    system_id, transport_number = cts_transport
    target_file = tmp_path / f"{transport_number}.xml"

    read_file_response = call_cts_transport_read_to_file(system_id, transport_number, str(target_file.resolve()))
    assert read_file_response.result is True
    assert target_file.exists()

    write_file_response = call_cts_transport_write_from_file(system_id, transport_number, str(target_file.resolve()))
    assert write_file_response.result is True


@pytest.mark.integration
def test_cts_transport_delete_removes_request(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    create_response = call_cts_transport_create(
        systemId=system_id,
        packageName="$TMP",
        requestText="Pytest CTS Delete",
        objectUri="/sap/bc/adt/oo/classes/YCDX_CL_120226",
        operation="I",
    )
    assert create_response.result is True
    assert create_response.data is not None
    transport_number = create_response.data.transportNumber

    delete_response = call_cts_transport_delete(system_id, transport_number)

    assert delete_response.result is True
