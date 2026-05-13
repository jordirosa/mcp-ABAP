import pytest

from connection.connection import call_login
from source.programs.includes import (
    IncludeCreateRequest,
    IncludeUpdateRequest,
    call_include_create,
    call_include_delete,
    call_include_lock,
    call_include_read,
    call_include_read_to_file,
    call_include_unlock,
    call_include_update,
    call_include_write_from_file,
)
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_program_include_crud(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_source_name("YCDXIN")

    try:
        create = call_include_create(
            systemId=system_id,
            request=IncludeCreateRequest(name=name, description="Pytest include", packageName="$TMP", language="EN", responsible="DEVELOPER"),
        )
        assert create.result is True

        source = "FORM ping.\nENDFORM.\n"
        lock = call_include_lock(system_id, name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_include_update(system_id, name, lock.data.lockHandle, IncludeUpdateRequest(source=source))
            assert update.result is True
        finally:
            call_include_unlock(system_id, name, lock.data.lockHandle)

        read = call_include_read(system_id, name)
        assert read.result is True and read.data is not None
        assert "FORM ping." in read.data.content

        local_file = tmp_path / f"{name}.abap"
        assert call_include_read_to_file(system_id, name, str(local_file)).result is True
        local_file.write_text("FORM pong.\nENDFORM.\n", encoding="utf-8")
        assert call_include_write_from_file(system_id, name, str(local_file)).result is True
    finally:
        call_include_delete(system_id, name)
