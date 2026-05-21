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


def test_call_login_returns_false_when_discovery_rejects_credentials(monkeypatch):
    """get_csrf_token must not store the session when SAP returns non-200."""
    from types import SimpleNamespace
    import requests

    fake_config = SimpleNamespace(
        id="A4H", server="https://fake", client="001", language="EN",
        user="INVENTADO", password="INVENTADO", verify_ssl=False,
    )
    stored = []

    class FakeResponse:
        status_code = 401
        headers = {}

    class FakeSession:
        headers = {}
        auth = None
        verify = None

        def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(connection, "get_system_config", lambda system_id: fake_config)
    monkeypatch.setattr(connection, "get_session", lambda system_id: None)
    monkeypatch.setattr(connection, "set_session", lambda system_id, value: stored.append((system_id, value)))
    monkeypatch.setattr("connection.connection.requests.Session", lambda: FakeSession())

    result = connection.call_login("A4H")

    assert result.result is False
    assert stored == [("A4H", None)]


def test_call_login_returns_false_when_csrf_token_missing(monkeypatch):
    """call_login must return False when discovery succeeds but returns no CSRF token."""
    from types import SimpleNamespace

    fake_config = SimpleNamespace(
        id="A4H", server="https://fake", client="001", language="EN",
        user="USER", password="PASS", verify_ssl=False,
    )
    stored = []

    class FakeResponse:
        status_code = 200
        headers = {}

    class FakeSession:
        headers = {}
        auth = None
        verify = None

        def get(self, url, headers=None):
            return FakeResponse()

        def update(self, d):
            self.headers.update(d)

    monkeypatch.setattr(connection, "get_system_config", lambda system_id: fake_config)
    monkeypatch.setattr(connection, "get_session", lambda system_id: None)
    monkeypatch.setattr(connection, "set_session", lambda system_id, value: stored.append((system_id, value)))
    monkeypatch.setattr("connection.connection.requests.Session", lambda: FakeSession())

    result = connection.call_login("A4H")

    assert result.result is False


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
