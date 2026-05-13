from datetime import datetime

import pytest

from connection.connection import call_login
from ddic.dataelements.dataelements import (
    DdicDataElementUpdateRequest,
    call_ddic_dataelement_create,
    call_ddic_dataelement_lock,
    call_ddic_dataelement_unlock,
    call_ddic_dataelement_update,
)
from ddic.domains.domains import (
    DdicDomainUpdateRequest,
    call_ddic_domain_create,
    call_ddic_domain_lock,
    call_ddic_domain_unlock,
    call_ddic_domain_update,
)
from ddic.tables.tables import (
    DdicTableUpdateRequest,
    call_ddic_table_create,
    call_ddic_table_lock,
    call_ddic_table_read,
    call_ddic_table_unlock,
    call_ddic_table_update,
)
from deletion.deletion import call_deletion_delete


def _unique_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


def _delete_table(system_id: str, name: str, transport_number: str = "") -> None:
    call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/tables/{name.lower()}",
        transportNumber=transport_number,
    )


def _delete_dataelement(system_id: str, name: str, transport_number: str = "") -> None:
    call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/dataelements/{name.lower()}",
        transportNumber=transport_number,
    )


def _delete_domain(system_id: str, name: str, transport_number: str = "") -> None:
    call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
        transportNumber=transport_number,
    )


def _update_domain(system_id: str, name: str, request: DdicDomainUpdateRequest, transport_number: str = ""):
    lock_response = call_ddic_domain_lock(system_id, name)
    assert lock_response.result is True
    assert lock_response.data is not None
    try:
        update_response = call_ddic_domain_update(
            systemId=system_id,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transport_number,
        )
    finally:
        call_ddic_domain_unlock(system_id, name, lock_response.data.lockHandle)
    return update_response


def _update_dataelement(system_id: str, name: str, request: DdicDataElementUpdateRequest, transport_number: str = ""):
    lock_response = call_ddic_dataelement_lock(system_id, name)
    assert lock_response.result is True
    assert lock_response.data is not None
    try:
        update_response = call_ddic_dataelement_update(
            systemId=system_id,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transport_number,
        )
    finally:
        call_ddic_dataelement_unlock(system_id, name, lock_response.data.lockHandle)
    return update_response


def _update_table(system_id: str, name: str, source: str, transport_number: str = ""):
    lock_response = call_ddic_table_lock(system_id, name)
    assert lock_response.result is True
    assert lock_response.data is not None
    try:
        update_response = call_ddic_table_update(
            systemId=system_id,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=DdicTableUpdateRequest(source=source),
            transportNumber=transport_number,
        )
    finally:
        call_ddic_table_unlock(system_id, name, lock_response.data.lockHandle)
    return update_response


def _table_source_builtin(name: str) -> str:
    return f"""@EndUserText.label : 'Pytest table'
@AbapCatalog.enhancement.category : #NOT_EXTENSIBLE
@AbapCatalog.tableCategory : #TRANSPARENT
@AbapCatalog.deliveryClass : #A
@AbapCatalog.dataMaintenance : #ALLOWED
define table {name.lower()} {{
  key mandt : abap.clnt not null;
  key id    : abap.numc(8) not null;
  txt       : abap.char(20);

}}"""


def _table_source_dataelement(name: str, dataelement_name: str) -> str:
    return f"""@EndUserText.label : 'Pytest table'
@AbapCatalog.enhancement.category : #NOT_EXTENSIBLE
@AbapCatalog.tableCategory : #TRANSPARENT
@AbapCatalog.deliveryClass : #A
@AbapCatalog.dataMaintenance : #ALLOWED
define table {name.lower()} {{
  key mandt : abap.clnt not null;
  key id    : {dataelement_name.lower()} not null;
  txt       : abap.char(20);

}}"""


@pytest.mark.integration
def test_ddic_table_tmp_builtin_source(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    table_name = _unique_name("YCDXTB")

    try:
        create_response = call_ddic_table_create(
            systemId=system_id,
            name=table_name,
            description="Pytest local built in table",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_table(system_id, table_name, _table_source_builtin(table_name))
        assert update_response.result is True

        read_response = call_ddic_table_read(system_id, table_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert f"define table {table_name.lower()}" in read_response.data.source
        assert "abap.numc(8)" in read_response.data.source
        assert "abap.char(20)" in read_response.data.source
    finally:
        _delete_table(system_id, table_name)


@pytest.mark.integration
def test_ddic_table_tmp_uses_dataelement(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXDM")
    dataelement_name = _unique_name("YCDXDE")
    table_name = _unique_name("YCDXTB")

    try:
        assert call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest local table domain",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        ).result is True
        assert _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(dataType="CHAR", length=10, outputLength=10),
        ).result is True

        assert call_ddic_dataelement_create(
            systemId=system_id,
            name=dataelement_name,
            description="Pytest local table data element",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        ).result is True
        assert _update_dataelement(
            system_id,
            dataelement_name,
            DdicDataElementUpdateRequest(typeKind="domain", typeName=domain_name, shortFieldLabel="Codigo", shortFieldLength=6),
        ).result is True

        assert call_ddic_table_create(
            systemId=system_id,
            name=table_name,
            description="Pytest local data element table",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        ).result is True
        assert _update_table(system_id, table_name, _table_source_dataelement(table_name, dataelement_name)).result is True

        read_response = call_ddic_table_read(system_id, table_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert dataelement_name.lower() in read_response.data.source
    finally:
        _delete_table(system_id, table_name)
        _delete_dataelement(system_id, dataelement_name)
        _delete_domain(system_id, domain_name)


@pytest.mark.integration
def test_ddic_table_transport_builtin_source(ddic_transport_package):
    system_id, package_name, transport_number = ddic_transport_package
    table_name = _unique_name("ZCDXTB")

    try:
        create_response = call_ddic_table_create(
            systemId=system_id,
            name=table_name,
            description="Pytest transport built in table",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_table(system_id, table_name, _table_source_builtin(table_name), transport_number)
        assert update_response.result is True

        read_response = call_ddic_table_read(system_id, table_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert f"define table {table_name.lower()}" in read_response.data.source
        assert "abap.numc(8)" in read_response.data.source
    finally:
        _delete_table(system_id, table_name, transport_number)


@pytest.mark.integration
def test_ddic_table_transport_uses_dataelement(ddic_transport_package):
    system_id, package_name, transport_number = ddic_transport_package
    domain_name = _unique_name("ZCDXDM")
    dataelement_name = _unique_name("ZCDXDE")
    table_name = _unique_name("ZCDXTB")

    try:
        assert call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest transport table domain",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        ).result is True
        assert _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(dataType="NUMC", length=10, outputLength=10, conversionExit="ALPHA"),
            transport_number,
        ).result is True

        assert call_ddic_dataelement_create(
            systemId=system_id,
            name=dataelement_name,
            description="Pytest transport table data element",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        ).result is True
        assert _update_dataelement(
            system_id,
            dataelement_name,
            DdicDataElementUpdateRequest(typeKind="domain", typeName=domain_name, shortFieldLabel="Codigo", shortFieldLength=6),
            transport_number,
        ).result is True

        assert call_ddic_table_create(
            systemId=system_id,
            name=table_name,
            description="Pytest transport data element table",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        ).result is True
        assert _update_table(system_id, table_name, _table_source_dataelement(table_name, dataelement_name), transport_number).result is True

        read_response = call_ddic_table_read(system_id, table_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert dataelement_name.lower() in read_response.data.source
    finally:
        _delete_table(system_id, table_name, transport_number)
        _delete_dataelement(system_id, dataelement_name, transport_number)
        _delete_domain(system_id, domain_name, transport_number)


@pytest.mark.integration
def test_ddic_table_delete_removes_object(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    table_name = _unique_name("YCDXDL")

    create_response = call_ddic_table_create(
        systemId=system_id,
        name=table_name,
        description="Pytest delete table",
        packageName="$TMP",
        language="EN",
        responsible="DEVELOPER",
    )
    assert create_response.result is True

    delete_response = call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/tables/{table_name.lower()}",
        transportNumber="",
    )
    assert delete_response.result is True

    read_response = call_ddic_table_read(system_id, table_name)
    assert read_response.result is False
