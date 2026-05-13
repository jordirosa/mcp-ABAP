import pytest

from connection.connection import call_login
from source.classes.classes import (
    ClassCreateRequest,
    ClassUpdateRequest,
    call_class_create,
    call_class_delete,
    call_class_lock,
    call_class_read,
    call_class_read_to_file,
    call_class_symbols_read,
    call_class_symbols_update,
    call_class_symbols_write_from_file,
    call_class_unlock,
    call_class_update,
    call_class_write_from_file,
)
from source.symbols import SourceSymbolsUpdateRequest
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_class_crud_and_symbols(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_source_name("YCDXCL")

    try:
        create = call_class_create(
            systemId=system_id,
            request=ClassCreateRequest(
                name=name,
                description="Pytest class",
                packageName="$TMP",
                language="EN",
                responsible="DEVELOPER",
                visibility="public",
                isFinal=True,
                includeTestClasses=False,
            ),
        )
        assert create.result is True

        source = (
            f"CLASS {name} DEFINITION PUBLIC FINAL CREATE PUBLIC.\n"
            "  PUBLIC SECTION.\n"
            "    METHODS ping RETURNING VALUE(rv_text) TYPE string.\n"
            "ENDCLASS.\n\n"
            f"CLASS {name} IMPLEMENTATION.\n"
            "  METHOD ping.\n"
            "    rv_text = `OK`.\n"
            "  ENDMETHOD.\n"
            "ENDCLASS.\n"
        )
        lock = call_class_lock(system_id, name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_class_update(system_id, name, lock.data.lockHandle, ClassUpdateRequest(source=source))
            assert update.result is True
        finally:
            call_class_unlock(system_id, name, lock.data.lockHandle)

        read = call_class_read(system_id, name)
        assert read.result is True and read.data is not None
        assert f"CLASS {name} DEFINITION" in read.data.content

        local_file = tmp_path / f"{name}.clas.abap"
        assert call_class_read_to_file(system_id, name, str(local_file)).result is True
        local_file.write_text(source.replace("`OK`", "`UPDATED`"), encoding="utf-8")
        assert call_class_write_from_file(system_id, name, str(local_file)).result is True

        assert call_class_symbols_update(system_id, name, SourceSymbolsUpdateRequest(content="@MaxLength:54\r\nT01=Texto clase\r\n")).result is True
        symbols_read = call_class_symbols_read(system_id, name)
        assert symbols_read.result is True and symbols_read.data is not None
        assert "T01=Texto clase" in symbols_read.data.content

        symbols_file = tmp_path / f"{name}.clas.symbols.txt"
        symbols_file.write_text("@MaxLength:54\r\nT01=Texto clase 2\r\n", encoding="utf-8")
        assert call_class_symbols_write_from_file(system_id, name, str(symbols_file)).result is True
    finally:
        call_class_delete(system_id, name)
