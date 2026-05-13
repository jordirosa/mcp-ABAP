import pytest

from connection.connection import call_login, call_logout, ensure_login, get_csrf_token
from configuration import get_session


@pytest.mark.integration
def test_call_login_opens_session_and_fetches_csrf(clean_sap_session):
    system_id = clean_sap_session

    response = call_login(system_id)

    assert response.result is True
    session = get_session(system_id)
    assert session is not None
    assert session.headers.get("X-CSRF-Token")


@pytest.mark.integration
def test_ensure_login_is_true_after_login(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    is_logged_in, message = ensure_login(system_id)

    assert is_logged_in is True
    assert message == ""


@pytest.mark.integration
def test_get_csrf_token_returns_token_and_reuses_session(clean_sap_session):
    system_id = clean_sap_session

    first_token = get_csrf_token(system_id)
    first_session = get_session(system_id)
    second_token = get_csrf_token(system_id)
    second_session = get_session(system_id)

    assert first_session is not None
    assert second_session is first_session
    assert first_token
    assert second_token


@pytest.mark.integration
def test_call_logout_clears_session(clean_sap_session):
    system_id = clean_sap_session
    login_response = call_login(system_id)
    assert login_response.result is True

    logout_response = call_logout(system_id)

    assert logout_response.result is True
    assert get_session(system_id) is None
