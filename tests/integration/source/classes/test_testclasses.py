import pytest

from connection.connection import call_login
from source.classes.classes import ClassCreateRequest, call_class_create, call_class_delete
from source.classes.testclasses import (
    ClassTestclassesUpdateRequest,
    call_class_testclasses_create,
    call_class_testclasses_read,
    call_class_testclasses_read_to_file,
    call_class_testclasses_update,
    call_class_testclasses_write_from_file,
)
from tests.integration.source.conftest import unique_source_name


@pytest.mark.integration
def test_source_class_testclasses_flow(clean_sap_session, tmp_path):
    system_id = clean_sap_session
    assert call_login(system_id).result is True
    name = unique_source_name("YCDXCL")

    try:
        create = call_class_create(
            systemId=system_id,
            request=ClassCreateRequest(
                name=name,
                description="Pytest class for testclasses",
                packageName="$TMP",
                language="EN",
                responsible="DEVELOPER",
                visibility="public",
                isFinal=True,
                includeTestClasses=False,
            ),
        )
        assert create.result is True

        assert call_class_testclasses_create(system_id, name).result is True
        assert call_class_testclasses_update(
            systemId=system_id,
            className=name,
            request=ClassTestclassesUpdateRequest(
                source='*"* use this source file for your ABAP unit test classes\nCLASS ltc_main DEFINITION FINAL FOR TESTING.\nENDCLASS.\n\nCLASS ltc_main IMPLEMENTATION.\nENDCLASS.\n'
            ),
        ).result is True

        read = call_class_testclasses_read(system_id, name)
        assert read.result is True and read.data is not None
        assert "CLASS ltc_main DEFINITION" in read.data.content

        tc_file = tmp_path / f"{name}.testclasses.abap"
        assert call_class_testclasses_read_to_file(system_id, name, str(tc_file)).result is True
        tc_file.write_text('*"* use this source file for your ABAP unit test classes\nCLASS ltc_main DEFINITION FINAL FOR TESTING.\n  PRIVATE SECTION.\n    METHODS dummy_test FOR TESTING.\nENDCLASS.\n\nCLASS ltc_main IMPLEMENTATION.\n  METHOD dummy_test.\n  ENDMETHOD.\nENDCLASS.\n', encoding="utf-8")
        assert call_class_testclasses_write_from_file(system_id, name, str(tc_file)).result is True
    finally:
        call_class_delete(system_id, name)
