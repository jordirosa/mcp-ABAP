from types import SimpleNamespace

from classrun import classrun


def test_classrun_uri_normalizes_and_encodes_name():
    assert classrun._classrun_uri(" yjrs_run_test ") == "/sap/bc/adt/oo/classrun/YJRS_RUN_TEST"


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
        {"headers": {"Accept": "text/plain"}},
    )]


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
