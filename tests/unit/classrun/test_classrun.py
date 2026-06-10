from types import SimpleNamespace

import requests

from classrun import classrun


def test_classrun_uri_normalizes_and_encodes_name():
    assert classrun._classrun_uri(" yjrs_run_test ") == "/sap/bc/adt/oo/classrun/YJRS_RUN_TEST"


def test_is_classrun_error_output_detects_sap_error_text():
    assert classrun._is_classrun_error_output(
        "Error: Class does not implement if_oo_adt_classrun~main method!"
    ) is True
    assert classrun._is_classrun_error_output("Hello world\n") is False


def test_clear_adt_context_cookie_preserves_authenticated_session_cookies():
    session = requests.Session()
    session.cookies.set("SAP_SESSIONID_A4H_001", "session", domain="example.test", path="/")
    session.cookies.set("sap-contextid", "context", domain="example.test", path="/sap/bc/adt")

    classrun._clear_adt_context_cookie(session)

    assert session.cookies.get("SAP_SESSIONID_A4H_001") == "session"
    assert "sap-contextid" not in session.cookies


def test_call_classrun_returns_401_when_not_logged_in(monkeypatch):
    monkeypatch.setattr(classrun, "ensure_login", lambda system_id: (False, "No session."))

    result = classrun.call_classrun_run("A4H", "YJRS_RUN_TEST")

    assert result.result is False
    assert result.httpCode == 401


def test_call_classrun_returns_400_for_missing_class_name(monkeypatch):
    monkeypatch.setattr(classrun, "ensure_login", lambda system_id: (True, ""))

    result = classrun.call_classrun_run("A4H", "")

    assert result.result is False
    assert result.httpCode == 400


def test_call_classrun_posts_to_correct_url_and_accepts_text_plain(monkeypatch):
    monkeypatch.setattr(classrun, "ensure_login", lambda system_id: (True, ""))

    captured = []

    class FakeSession:
        def post(self, url, **kwargs):
            captured.append((url, kwargs))
            return SimpleNamespace(
                status_code=200,
                reason="OK",
                text="Hello world\n",
                headers={"Content-Type": "text/plain"},
            )

    monkeypatch.setattr(classrun, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake:8443"))
    monkeypatch.setattr(classrun, "get_session", lambda system_id: FakeSession())

    result = classrun.call_classrun_run("A4H", "yjrs_run_test")

    assert result.result is True
    assert result.data.output == "Hello world\n"
    assert result.data.className == "YJRS_RUN_TEST"
    assert result.data.uri == "/sap/bc/adt/oo/classrun/YJRS_RUN_TEST"
    assert captured == [(
        "https://fake:8443/sap/bc/adt/oo/classrun/YJRS_RUN_TEST",
        {"headers": {
            "X-sap-adt-sessiontype": "stateful",
            "Accept": "text/plain",
        }},
    )]


def test_call_classrun_returns_failure_for_error_text_inside_http_200(monkeypatch):
    monkeypatch.setattr(classrun, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(classrun, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(
        classrun,
        "get_session",
        lambda system_id: type(
            "S",
            (),
            {
                "post": lambda self, url, **kw: SimpleNamespace(
                    status_code=200,
                    reason="OK",
                    text="Error: Class does not implement if_oo_adt_classrun~main method!",
                    headers={"Content-Type": "text/plain"},
                )
            },
        )(),
    )

    result = classrun.call_classrun_run("A4H", "YJRS_RUN_TEST")

    assert result.result is False
    assert result.httpCode == 200
    assert result.data is None
    assert "Class does not implement" in result.message


def test_call_classrun_returns_error_when_sap_rejects_request(monkeypatch):
    monkeypatch.setattr(classrun, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(classrun, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(
        classrun,
        "get_session",
        lambda system_id: type(
            "S",
            (),
            {
                "post": lambda self, url, **kw: SimpleNamespace(
                    status_code=404,
                    reason="Not Found",
                    text="Class not found",
                    headers={},
                )
            },
        )(),
    )

    result = classrun.call_classrun_run("A4H", "ZCL_MISSING")

    assert result.result is False
    assert result.httpCode == 404
    assert "Class not found" in result.message
