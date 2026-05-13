import pytest

from connection.connection import call_login
from source.programs.programs import (
    ProgramCreateRequest,
    ProgramUpdateRequest,
    call_program_create,
    call_program_delete,
    call_program_lock,
    call_program_read,
    call_program_read_to_file,
    call_program_symbols_read,
    call_program_symbols_update,
    call_program_symbols_write_from_file,
    call_program_unlock,
    call_program_update,
    call_program_write_from_file,
)
from source.symbols import SourceSymbolsUpdateRequest
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_program_crud_and_symbols(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_source_name("YCDXPG")

    try:
        create = call_program_create(
            systemId=system_id,
            request=ProgramCreateRequest(name=name, description="Pytest program", packageName="$TMP", language="EN", responsible="DEVELOPER"),
        )
        assert create.result is True

        source = f'REPORT {name}.\n\nWRITE `HELLO`.\n'
        lock = call_program_lock(system_id, name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_program_update(system_id, name, lock.data.lockHandle, ProgramUpdateRequest(source=source))
            assert update.result is True
        finally:
            call_program_unlock(system_id, name, lock.data.lockHandle)

        read = call_program_read(system_id, name)
        assert read.result is True and read.data is not None
        assert f"REPORT {name}." in read.data.content

        local_file = tmp_path / f"{name}.abap"
        assert call_program_read_to_file(system_id, name, str(local_file)).result is True
        local_file.write_text(f'REPORT {name}.\n\nWRITE `UPDATED`.\n', encoding="utf-8")
        assert call_program_write_from_file(system_id, name, str(local_file)).result is True

        assert call_program_symbols_update(
            systemId=system_id,
            name=name,
            request=SourceSymbolsUpdateRequest(content="@MaxLength:54\r\nT01=Texto programa\r\n"),
        ).result is True
        symbols_read = call_program_symbols_read(system_id, name)
        assert symbols_read.result is True and symbols_read.data is not None
        assert "T01=Texto programa" in symbols_read.data.content

        symbols_file = tmp_path / f"{name}.symbols.txt"
        symbols_file.write_text("@MaxLength:54\r\nT01=Texto programa 2\r\n", encoding="utf-8")
        assert call_program_symbols_write_from_file(system_id, name, str(symbols_file)).result is True
    finally:
        call_program_delete(system_id, name)
