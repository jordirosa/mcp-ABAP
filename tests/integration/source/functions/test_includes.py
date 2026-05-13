import pytest

from connection.connection import call_login
from source.functions.groups import FunctionGroupCreateRequest, call_function_group_create, call_function_group_delete
from source.functions.includes import (
    FunctionIncludeCreateRequest,
    FunctionIncludeUpdateRequest,
    call_function_include_create,
    call_function_include_delete,
    call_function_include_lock,
    call_function_include_read,
    call_function_include_read_to_file,
    call_function_include_unlock,
    call_function_include_update,
    call_function_include_write_from_file,
)
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_function_include_crud(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    fg_name = unique_source_name("YCDXFG")
    include_name = f"L{fg_name}F01"

    try:
        assert call_function_group_create(
            systemId=system_id,
            request=FunctionGroupCreateRequest(name=fg_name, description="Pytest function group", packageName="$TMP", language="EN", responsible="DEVELOPER"),
        ).result is True

        create = call_function_include_create(system_id, FunctionIncludeCreateRequest(functionGroupName=fg_name, name=include_name, description="Pytest function include"))
        assert create.result is True

        lock = call_function_include_lock(system_id, fg_name, include_name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_function_include_update(system_id, fg_name, include_name, lock.data.lockHandle, FunctionIncludeUpdateRequest(source="FORM ping.\nENDFORM.\n"))
            assert update.result is True
        finally:
            call_function_include_unlock(system_id, fg_name, include_name, lock.data.lockHandle)

        read = call_function_include_read(system_id, fg_name, include_name)
        assert read.result is True and read.data is not None
        assert "FORM ping." in read.data.content

        local_file = tmp_path / f"{include_name}.finc.abap"
        assert call_function_include_read_to_file(system_id, fg_name, include_name, str(local_file)).result is True
        local_file.write_text("FORM pong.\nENDFORM.\n", encoding="utf-8")
        assert call_function_include_write_from_file(system_id, fg_name, include_name, str(local_file)).result is True
    finally:
        call_function_include_delete(system_id, fg_name, include_name)
        call_function_group_delete(system_id, fg_name)
