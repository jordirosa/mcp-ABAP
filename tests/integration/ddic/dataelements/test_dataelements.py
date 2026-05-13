from datetime import datetime

import pytest

from connection.connection import call_login
from ddic.dataelements.dataelements import (
    DdicDataElementUpdateRequest,
    call_ddic_dataelement_create,
    call_ddic_dataelement_lock,
    call_ddic_dataelement_read,
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
from deletion.deletion import call_deletion_delete


def _unique_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"


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


@pytest.mark.integration
def test_ddic_dataelement_tmp_builtin_char(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    element_name = _unique_name("YCDXDE")

    try:
        create_response = call_ddic_dataelement_create(
            systemId=system_id,
            name=element_name,
            description="Pytest local CHAR data element",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_dataelement(
            system_id,
            element_name,
            DdicDataElementUpdateRequest(
                description="Pytest local CHAR data element",
                typeKind="predefinedAbapType",
                dataType="CHAR",
                dataTypeLength=12,
                shortFieldLabel="Clave",
                shortFieldLength=5,
                mediumFieldLabel="Clave local",
                mediumFieldLength=11,
                longFieldLabel="Clave local larga",
                longFieldLength=17,
                headingFieldLabel="Clave encabezado",
                headingFieldLength=16,
                defaultComponentName="FIELD",
            ),
        )
        assert update_response.result is True

        read_response = call_ddic_dataelement_read(system_id, element_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.packageName == "$TMP"
        assert read_response.data.typeKind == "predefinedAbapType"
        assert read_response.data.dataType == "CHAR"
        assert read_response.data.dataTypeLength == 12
        assert read_response.data.shortFieldLabel == "Clave"
        assert read_response.data.defaultComponentName == "FIELD"
    finally:
        _delete_dataelement(system_id, element_name)


@pytest.mark.integration
def test_ddic_dataelement_tmp_builtin_decimal(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    element_name = _unique_name("YCDXNM")

    try:
        create_response = call_ddic_dataelement_create(
            systemId=system_id,
            name=element_name,
            description="Pytest local DEC data element",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_dataelement(
            system_id,
            element_name,
            DdicDataElementUpdateRequest(
                description="Pytest local DEC data element",
                typeKind="predefinedAbapType",
                dataType="DEC",
                dataTypeLength=13,
                dataTypeDecimals=2,
                shortFieldLabel="Importe",
                shortFieldLength=6,
                setGetParameter="WRB",
                changeDocument=True,
            ),
        )
        assert update_response.result is True

        read_response = call_ddic_dataelement_read(system_id, element_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.dataType == "DEC"
        assert read_response.data.dataTypeLength == 13
        assert read_response.data.dataTypeDecimals == 2
        assert read_response.data.setGetParameter == "WRB"
        assert read_response.data.changeDocument is True
    finally:
        _delete_dataelement(system_id, element_name)


@pytest.mark.integration
def test_ddic_dataelement_tmp_uses_domain(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    domain_name = _unique_name("YCDXDM")
    element_name = _unique_name("YCDXDE")

    try:
        domain_create = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest local domain for data element",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert domain_create.result is True

        domain_update = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="CHAR",
                length=10,
                outputLength=10,
            ),
        )
        assert domain_update.result is True

        element_create = call_ddic_dataelement_create(
            systemId=system_id,
            name=element_name,
            description="Pytest local domain based data element",
            packageName="$TMP",
            language="EN",
            responsible="DEVELOPER",
        )
        assert element_create.result is True

        element_update = _update_dataelement(
            system_id,
            element_name,
            DdicDataElementUpdateRequest(
                description="Pytest local domain based data element",
                typeKind="domain",
                typeName=domain_name,
                shortFieldLabel="Dominio",
                shortFieldLength=7,
            ),
        )
        assert element_update.result is True

        read_response = call_ddic_dataelement_read(system_id, element_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.typeKind == "domain"
        assert read_response.data.typeName == domain_name
        assert read_response.data.packageName == "$TMP"
    finally:
        _delete_dataelement(system_id, element_name)
        _delete_domain(system_id, domain_name)


@pytest.mark.integration
def test_ddic_dataelement_transport_builtin(ddic_transport_package):
    system_id, package_name, transport_number = ddic_transport_package
    element_name = _unique_name("ZCDXDE")

    try:
        create_response = call_ddic_dataelement_create(
            systemId=system_id,
            name=element_name,
            description="Pytest transport built in data element",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        )
        assert create_response.result is True

        update_response = _update_dataelement(
            system_id,
            element_name,
            DdicDataElementUpdateRequest(
                description="Pytest transport built in data element",
                typeKind="predefinedAbapType",
                dataType="NUMC",
                dataTypeLength=8,
                shortFieldLabel="Numero",
                shortFieldLength=6,
                deactivateInputHistory=True,
            ),
            transport_number,
        )
        assert update_response.result is True

        read_response = call_ddic_dataelement_read(system_id, element_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.packageName == package_name
        assert read_response.data.dataType == "NUMC"
        assert read_response.data.deactivateInputHistory is True
    finally:
        _delete_dataelement(system_id, element_name, transport_number)


@pytest.mark.integration
def test_ddic_dataelement_transport_uses_domain(ddic_transport_package):
    system_id, package_name, transport_number = ddic_transport_package
    domain_name = _unique_name("ZCDXDM")
    element_name = _unique_name("ZCDXDE")

    try:
        domain_create = call_ddic_domain_create(
            systemId=system_id,
            name=domain_name,
            description="Pytest transport domain",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        )
        assert domain_create.result is True

        domain_update = _update_domain(
            system_id,
            domain_name,
            DdicDomainUpdateRequest(
                dataType="NUMC",
                length=10,
                outputLength=10,
                conversionExit="ALPHA",
            ),
            transport_number,
        )
        assert domain_update.result is True

        element_create = call_ddic_dataelement_create(
            systemId=system_id,
            name=element_name,
            description="Pytest transport domain based data element",
            packageName=package_name,
            transportNumber=transport_number,
            language="EN",
            responsible="DEVELOPER",
        )
        assert element_create.result is True

        element_update = _update_dataelement(
            system_id,
            element_name,
            DdicDataElementUpdateRequest(
                description="Pytest transport domain based data element",
                typeKind="domain",
                typeName=domain_name,
                mediumFieldLabel="Elemento transporte",
                mediumFieldLength=18,
            ),
            transport_number,
        )
        assert element_update.result is True

        read_response = call_ddic_dataelement_read(system_id, element_name)
        assert read_response.result is True
        assert read_response.data is not None
        assert read_response.data.packageName == package_name
        assert read_response.data.typeKind == "domain"
        assert read_response.data.typeName == domain_name
    finally:
        _delete_dataelement(system_id, element_name, transport_number)
        _delete_domain(system_id, domain_name, transport_number)


@pytest.mark.integration
def test_ddic_dataelement_delete_removes_object(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    element_name = _unique_name("YCDXDL")

    create_response = call_ddic_dataelement_create(
        systemId=system_id,
        name=element_name,
        description="Pytest delete data element",
        packageName="$TMP",
        language="EN",
        responsible="DEVELOPER",
    )
    assert create_response.result is True

    delete_response = call_deletion_delete(
        systemId=system_id,
        objectUri=f"/sap/bc/adt/ddic/dataelements/{element_name.lower()}",
        transportNumber="",
    )
    assert delete_response.result is True

    read_response = call_ddic_dataelement_read(system_id, element_name)
    assert read_response.result is False
