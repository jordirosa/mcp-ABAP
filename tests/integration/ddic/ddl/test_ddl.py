import pytest

from connection.connection import call_login
from ddic.ddl.ddl import (
    DdicDdlSourceUpdateRequest,
    call_ddic_ddl_source_create,
    call_ddic_ddl_source_delete,
    call_ddic_ddl_source_lock,
    call_ddic_ddl_source_read,
    call_ddic_ddl_source_read_to_file,
    call_ddic_ddl_source_unlock,
    call_ddic_ddl_source_update,
    call_ddic_ddl_source_write_from_file,
)
from tests.integration.ddic.conftest import unique_ddic_name


def _cds_source(name: str) -> str:
    return (
        f"@EndUserText.label : 'Pytest CDS'\n"
        f"define view entity {name}\n"
        f"  as select from t000\n"
        f"{{\n"
        f"  key mandt\n"
        f"}}"
    )


def _update_ddl_source(system_id: str, name: str, source: str, transport_number: str = ""):
    lock = call_ddic_ddl_source_lock(system_id, name)
    assert lock.result is True and lock.data is not None
    try:
        update = call_ddic_ddl_source_update(
            systemId=system_id,
            name=name,
            lockHandle=lock.data.lockHandle,
            request=DdicDdlSourceUpdateRequest(source=source),
            transportNumber=transport_number,
        )
    finally:
        call_ddic_ddl_source_unlock(system_id, name, lock.data.lockHandle)
    return update


@pytest.mark.integration
def test_ddic_ddl_source_tmp_crud_and_file_transfer(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_ddic_name("YCDXCDS")

    try:
        create = call_ddic_ddl_source_create(
            systemId=system_id,
            name=name,
            description="Pytest local CDS",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create.result is True
        assert create.data is not None
        assert create.data.name == name
        assert create.data.packageName == "$TMP"
        assert create.data.description == "Pytest local CDS"

        update = _update_ddl_source(system_id, name, _cds_source(name))
        assert update.result is True

        read = call_ddic_ddl_source_read(system_id, name)
        assert read.result is True and read.data is not None
        assert name.lower() in read.data.source.lower()
        assert "define view entity" in read.data.source
        assert "select from t000" in read.data.source

        local_file = tmp_path / f"{name}.cds"
        assert call_ddic_ddl_source_read_to_file(system_id, name, str(local_file)).result is True
        assert local_file.exists()

        updated_source = _cds_source(name).replace("Pytest CDS", "Pytest CDS Updated")
        local_file.write_text(updated_source, encoding="utf-8")
        assert call_ddic_ddl_source_write_from_file(system_id, name, str(local_file)).result is True

        read_after_upload = call_ddic_ddl_source_read(system_id, name)
        assert read_after_upload.result is True and read_after_upload.data is not None
        assert "Pytest CDS Updated" in read_after_upload.data.source
    finally:
        call_ddic_ddl_source_delete(system_id, name)
