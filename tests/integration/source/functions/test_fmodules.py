import pytest

from connection.connection import call_login
from source.functions.fmodule import (
    FunctionModuleCreateRequest,
    FunctionModuleUpdateRequest,
    call_function_module_create,
    call_function_module_delete,
    call_function_module_lock,
    call_function_module_read,
    call_function_module_read_to_file,
    call_function_module_unlock,
    call_function_module_update,
    call_function_module_write_from_file,
)
from source.functions.groups import FunctionGroupCreateRequest, call_function_group_create, call_function_group_delete
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_function_module_crud(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    fg_name = unique_source_name("YCDXFG")
    fm_name = unique_source_name("YCDXFM")

    try:
        assert call_function_group_create(
            systemId=system_id,
            request=FunctionGroupCreateRequest(name=fg_name, description="Pytest function group", packageName="$TMP", language="EN", responsible="DEVELOPER"),
        ).result is True

        create = call_function_module_create(system_id, FunctionModuleCreateRequest(functionGroupName=fg_name, name=fm_name, description="Pytest function module"))
        assert create.result is True

        read = call_function_module_read(system_id, fg_name, fm_name)
        assert read.result is True and read.data is not None
        assert f"FUNCTION {fm_name}" in read.data.content

        source = read.data.content.replace("ENDFUNCTION.", '  " updated\nENDFUNCTION.')
        lock = call_function_module_lock(system_id, fg_name, fm_name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_function_module_update(system_id, fg_name, fm_name, lock.data.lockHandle, FunctionModuleUpdateRequest(source=source))
            assert update.result is True
        finally:
            call_function_module_unlock(system_id, fg_name, fm_name, lock.data.lockHandle)

        local_file = tmp_path / f"{fm_name}.fmod.abap"
        assert call_function_module_read_to_file(system_id, fg_name, fm_name, str(local_file)).result is True
        local_file.write_text(source.replace('" updated', '" file'), encoding="utf-8")
        assert call_function_module_write_from_file(system_id, fg_name, fm_name, str(local_file)).result is True
    finally:
        call_function_module_delete(system_id, fg_name, fm_name)
        call_function_group_delete(system_id, fg_name)
