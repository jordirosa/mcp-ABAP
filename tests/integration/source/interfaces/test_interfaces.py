import pytest

from connection.connection import call_login
from source.interfaces.interfaces import (
    InterfaceCreateRequest,
    InterfaceUpdateRequest,
    call_interface_create,
    call_interface_delete,
    call_interface_lock,
    call_interface_read,
    call_interface_read_to_file,
    call_interface_unlock,
    call_interface_update,
    call_interface_write_from_file,
)
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_interface_crud(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_source_name("YCDXIF")

    try:
        create = call_interface_create(
            systemId=system_id,
            request=InterfaceCreateRequest(name=name, description="Pytest interface", packageName="$TMP", language="EN", responsible="DEVELOPER"),
        )
        assert create.result is True

        source = f"INTERFACE {name} PUBLIC.\n  METHODS ping RETURNING VALUE(rv_text) TYPE string.\nENDINTERFACE.\n"
        lock = call_interface_lock(system_id, name)
        assert lock.result is True and lock.data is not None
        try:
            update = call_interface_update(system_id, name, lock.data.lockHandle, InterfaceUpdateRequest(source=source))
            assert update.result is True
        finally:
            call_interface_unlock(system_id, name, lock.data.lockHandle)

        read = call_interface_read(system_id, name)
        assert read.result is True and read.data is not None
        assert f"INTERFACE {name} PUBLIC." in read.data.content

        local_file = tmp_path / f"{name}.intf.abap"
        assert call_interface_read_to_file(system_id, name, str(local_file)).result is True
        local_file.write_text(source.replace("ping", "pong"), encoding="utf-8")
        assert call_interface_write_from_file(system_id, name, str(local_file)).result is True
    finally:
        call_interface_delete(system_id, name)
