from datetime import datetime

import pytest

from connection.connection import call_login
from cts.cts import call_cts_transport_create, call_cts_transport_delete
from deletion.deletion import call_deletion_delete
from source.programs.programs import ProgramCreateRequest, call_program_create, call_program_read


def _unique_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


@pytest.mark.integration
def test_deletion_deletes_local_program(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    program_name = _unique_name("YCDXDL")

    create_response = call_program_create(
        systemId=system_id,
        request=ProgramCreateRequest(
            name=program_name,
            description="Pytest local deletion program",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        ),
    )
    assert create_response.result is True

    delete_response = call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/programs/programs/{program_name}",
        transportNumber="",
    )
    assert delete_response.result is True
    assert delete_response.data is not None
    assert delete_response.data.isDeleted is True
    assert delete_response.data.name == program_name

    read_response = call_program_read(system_id, program_name)
    assert read_response.result is False


@pytest.mark.integration
def test_deletion_deletes_transportable_program(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    program_name = _unique_name("ZCDXDL")

    transport_response = call_cts_transport_create(
        systemId=system_id,
        packageName="$TMP",
        requestText="Pytest deletion",
        objectUri="/sap/bc/adt/oo/classes/YCDX_CL_120226",
        operation="I",
    )
    assert transport_response.result is True
    assert transport_response.data is not None
    transport_number = transport_response.data.transportNumber

    try:
        create_response = call_program_create(
            systemId=system_id,
            request=ProgramCreateRequest(
                name=program_name,
                description="Pytest transport deletion program",
                packageName="$TMP",
                language="EN",
                responsible="DEVELOPER",
            ),
            transportNumber=transport_number,
        )
        assert create_response.result is True

        delete_response = call_deletion_delete(
            systemId=system_id,
            objectUri=f"/sap/bc/adt/programs/programs/{program_name}",
            transportNumber=transport_number,
        )
        assert delete_response.result is True
        assert delete_response.data is not None
        assert delete_response.data.isDeleted is True
        assert delete_response.data.name == program_name

        read_response = call_program_read(system_id, program_name)
        assert read_response.result is False
    finally:
        call_cts_transport_delete(system_id, transport_number)
