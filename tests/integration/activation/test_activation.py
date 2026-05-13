from datetime import datetime

import pytest

from activation.activation import (
    ActivationActivateRequest,
    ActivationObjectReference,
    call_activation_activate,
)
from connection.connection import call_login
from source.programs.programs import ProgramCreateRequest, call_program_create, call_program_delete


def _unique_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


@pytest.mark.integration
def test_activation_activates_single_program(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    program_name = _unique_name("YCDXPG")

    try:
        create_response = call_program_create(
            systemId=system_id,
            request=ProgramCreateRequest(
                name=program_name,
                description="Pytest activation program",
                packageName="$TMP",
                language="EN",
                responsible="DEVELOPER",
            ),
        )
        assert create_response.result is True
        assert create_response.data is not None

        activation_response = call_activation_activate(
            systemId=system_id,
            request=ActivationActivateRequest(
                objects=[
                    ActivationObjectReference(
                        uri=create_response.data.uri,
                        name=create_response.data.name,
                    )
                ],
                preauditRequested=True,
            ),
        )
        assert activation_response.httpCode == 200
        assert activation_response.data is not None
        assert activation_response.data.activationExecuted is True
    finally:
        call_program_delete(system_id, program_name)


@pytest.mark.integration
def test_activation_activates_multiple_programs_in_pack(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    first_name = _unique_name("YCDXPA")
    second_name = _unique_name("YCDXPB")

    try:
        first_create = call_program_create(
            systemId=system_id,
            request=ProgramCreateRequest(
                name=first_name,
                description="Pytest activation pack 1",
                packageName="$TMP",
                language="EN",
                responsible="DEVELOPER",
            ),
        )
        second_create = call_program_create(
            systemId=system_id,
            request=ProgramCreateRequest(
                name=second_name,
                description="Pytest activation pack 2",
                packageName="$TMP",
                language="EN",
                responsible="DEVELOPER",
            ),
        )
        assert first_create.result is True
        assert second_create.result is True
        assert first_create.data is not None
        assert second_create.data is not None

        activation_response = call_activation_activate(
            systemId=system_id,
            request=ActivationActivateRequest(
                objects=[
                    ActivationObjectReference(uri=first_create.data.uri, name=first_create.data.name),
                    ActivationObjectReference(uri=second_create.data.uri, name=second_create.data.name),
                ],
                preauditRequested=True,
            ),
        )
        assert activation_response.httpCode == 200
        assert activation_response.data is not None
        assert activation_response.data.activationExecuted is True
        assert len(activation_response.data.messages) >= 0
    finally:
        call_program_delete(system_id, first_name)
        call_program_delete(system_id, second_name)
