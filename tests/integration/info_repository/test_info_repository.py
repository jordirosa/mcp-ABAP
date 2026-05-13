import pytest

from connection.connection import call_login
from info_repository.info_repository import call_info_repository_search


@pytest.mark.integration
def test_info_repository_search_table_with_object_type(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True

    response = call_info_repository_search(system_id, "SFLIGHT", 10, "TABL")
    assert response.result is True
    assert response.data is not None
    assert response.data.totalCount >= 1
    assert any(item.name == "SFLIGHT" and item.type == "TABL/DT" for item in response.data.objectReferences)


@pytest.mark.integration
def test_info_repository_search_without_object_type_returns_multiple_kinds(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True

    response = call_info_repository_search(system_id, "SFLIGHT", 10)
    assert response.result is True
    assert response.data is not None
    assert response.data.totalCount >= 1
    assert any(item.name == "SFLIGHT" for item in response.data.objectReferences)


@pytest.mark.integration
def test_info_repository_search_program_pattern(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True

    response = call_info_repository_search(system_id, "YCDX*", 10, "PROG")
    assert response.result is True
    assert response.data is not None
    assert all(item.type.startswith("PROG/") for item in response.data.objectReferences)


@pytest.mark.integration
def test_info_repository_search_class_pattern(clean_sap_session):
    system_id = clean_sap_session
    assert call_login(system_id).result is True

    response = call_info_repository_search(system_id, "YJRS*", 10, "CLAS")
    assert response.result is True
    assert response.data is not None
    assert response.data.totalCount >= 1
    assert all(item.type.startswith("CLAS/") for item in response.data.objectReferences)
