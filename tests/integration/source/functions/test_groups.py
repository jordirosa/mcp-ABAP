import pytest

from connection.connection import call_login
from source.functions.groups import (
    FunctionGroupCreateRequest,
    FunctionGroupUpdateRequest,
    call_function_group_create,
    call_function_group_delete,
    call_function_group_lock,
    call_function_group_read,
    call_function_group_read_to_file,
    call_function_group_symbols_read,
    call_function_group_symbols_update,
    call_function_group_symbols_write_from_file,
    call_function_group_unlock,
    call_function_group_update,
    call_function_group_write_from_file,
)
from source.symbols import SourceSymbolsUpdateRequest
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_function_group_crud_and_symbols(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_source_name("YCDXFG")

    try:
        create = call_function_group_create(
            systemId=system_id,
            request=FunctionGroupCreateRequest(name=name, description="Pytest function group", packageName="$TMP", language="EN", responsible="DEVELOPER"),
        )
        assert create.result is True

        source = f"FUNCTION-POOL {name}.\n"
        lock = call_function_group_lock(system_id, name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_function_group_update(system_id, name, lock.data.lockHandle, FunctionGroupUpdateRequest(source=source))
            assert update.result is True
        finally:
            call_function_group_unlock(system_id, name, lock.data.lockHandle)

        read = call_function_group_read(system_id, name)
        assert read.result is True and read.data is not None
        assert f"FUNCTION-POOL {name}." in read.data.content

        local_file = tmp_path / f"{name}.fugr.abap"
        assert call_function_group_read_to_file(system_id, name, str(local_file)).result is True
        local_file.write_text(source + '" comment\n', encoding="utf-8")
        assert call_function_group_write_from_file(system_id, name, str(local_file)).result is True

        assert call_function_group_symbols_update(system_id, name, SourceSymbolsUpdateRequest(content="@MaxLength:54\r\nT01=Texto fg\r\n")).result is True
        symbols_read = call_function_group_symbols_read(system_id, name)
        assert symbols_read.result is True and symbols_read.data is not None
        assert "T01=Texto fg" in symbols_read.data.content

        symbols_file = tmp_path / f"{name}.fugr.symbols.txt"
        symbols_file.write_text("@MaxLength:54\r\nT01=Texto fg 2\r\n", encoding="utf-8")
        assert call_function_group_symbols_write_from_file(system_id, name, str(symbols_file)).result is True
    finally:
        call_function_group_delete(system_id, name)
