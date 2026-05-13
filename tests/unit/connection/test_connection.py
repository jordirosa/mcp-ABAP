from types import SimpleNamespace

from connection import connection


def test_build_adt_headers_defaults():
    headers = connection.build_adt_headers()

    assert headers == {"X-sap-adt-sessiontype": "stateless"}


def test_build_adt_headers_with_csrf_and_extra():
    headers = connection.build_adt_headers(
        sessionType="stateful",
        includeCsrfToken=True,
        extra={"Accept": "application/xml"},
    )

    assert headers == {
        "X-sap-adt-sessiontype": "stateful",
        "X-CSRF-Token": "Fetch",
        "Accept": "application/xml",
    }


def test_ensure_login_requires_existing_session(monkeypatch):
    monkeypatch.setattr(connection, "get_session", lambda system_id: None)

    is_logged_in, message = connection.ensure_login("A4H")

    assert is_logged_in is False
    assert "Login required for system A4H" in message


def test_ensure_login_accepts_existing_session(monkeypatch):
    monkeypatch.setattr(connection, "get_session", lambda system_id: object())

    is_logged_in, message = connection.ensure_login("A4H")

    assert is_logged_in is True
    assert message == ""


def test_call_logout_closes_existing_session(monkeypatch):
    class DummySession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    session = DummySession()
    cleared = []

    monkeypatch.setattr(connection, "get_system_config", lambda system_id: SimpleNamespace(id="A4H"))
    monkeypatch.setattr(connection, "get_session", lambda system_id: session)
    monkeypatch.setattr(connection, "set_session", lambda system_id, value: cleared.append((system_id, value)))

    response = connection.call_logout("A4H")

    assert response.result is True
    assert session.closed is True
    assert cleared == [("A4H", None)]
