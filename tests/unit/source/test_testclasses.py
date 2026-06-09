from types import SimpleNamespace

import pytest

from source.classes import testclasses


def _lock_response():
    return SimpleNamespace(
        result=True,
        data=SimpleNamespace(lockHandle="LOCK HANDLE"),
        httpCode=200,
        httpReason="OK",
        message="",
    )


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return SimpleNamespace(
            status_code=400,
            reason="Bad Request",
            text="Expected test rejection",
            headers={},
        )

    def put(self, url, **kwargs):
        self.calls.append(("put", url, kwargs))
        return SimpleNamespace(
            status_code=400,
            reason="Bad Request",
            text="Expected test rejection",
            headers={},
        )


def test_testclasses_lock_targets_testclasses_include(monkeypatch):
    calls = []

    class LockSession:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(
                status_code=200,
                reason="OK",
                text="""<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0"><asx:values><DATA><LOCK_HANDLE>LOCK</LOCK_HANDLE><CORRNR>A4HK900123</CORRNR><IS_LOCAL></IS_LOCAL></DATA></asx:values></asx:abap>""",
                headers={},
            )

    monkeypatch.setattr(testclasses, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(testclasses, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(testclasses, "get_session", lambda system_id: LockSession())

    response = testclasses.call_class_testclasses_lock("A4H", "ZCL_TEST")

    assert response.result is True
    assert calls[0][0] == "https://fake/sap/bc/adt/oo/classes/ZCL_TEST/includes/testclasses?_action=LOCK&accessMode=MODIFY"


def test_testclasses_unlock_targets_testclasses_include(monkeypatch):
    calls = []

    class UnlockSession:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=200, reason="OK", text="", headers={})

    monkeypatch.setattr(testclasses, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(testclasses, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(testclasses, "get_session", lambda system_id: UnlockSession())

    response = testclasses.call_class_testclasses_unlock("A4H", "ZCL_TEST", "LOCK HANDLE")

    assert response.result is True
    assert calls[0][0] == "https://fake/sap/bc/adt/oo/classes/ZCL_TEST/includes/testclasses?_action=UNLOCK&lockHandle=LOCK%20HANDLE"


def test_testclasses_create_locks_parent_class(monkeypatch):
    session = FakeSession()
    parent_lock_calls = []
    include_lock_calls = []
    monkeypatch.setattr(testclasses, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(testclasses, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(testclasses, "get_session", lambda system_id: session)
    monkeypatch.setattr(
        testclasses,
        "call_class_lock",
        lambda system_id, name: parent_lock_calls.append((system_id, name)) or _lock_response(),
    )
    monkeypatch.setattr(testclasses, "call_class_unlock", lambda system_id, name, lock_handle: None)
    monkeypatch.setattr(
        testclasses,
        "call_class_testclasses_lock",
        lambda system_id, name: include_lock_calls.append((system_id, name)) or _lock_response(),
    )

    testclasses.call_class_testclasses_create("A4H", "ZCL_TEST")

    assert parent_lock_calls == [("A4H", "ZCL_TEST")]
    assert include_lock_calls == []


def test_testclasses_update_locks_testclasses_include(monkeypatch):
    session = FakeSession()
    parent_lock_calls = []
    include_lock_calls = []
    monkeypatch.setattr(testclasses, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(testclasses, "get_session", lambda system_id: session)
    monkeypatch.setattr(
        testclasses,
        "call_class_lock",
        lambda system_id, name: parent_lock_calls.append((system_id, name)) or _lock_response(),
    )
    monkeypatch.setattr(
        testclasses,
        "call_class_testclasses_lock",
        lambda system_id, name: include_lock_calls.append((system_id, name)) or _lock_response(),
    )
    monkeypatch.setattr(testclasses, "call_class_testclasses_unlock", lambda system_id, name, lock_handle: None)

    testclasses.call_class_testclasses_update(
        "A4H",
        "ZCL_TEST",
        testclasses.ClassTestclassesUpdateRequest(source="CLASS ltc_test DEFINITION FOR TESTING. ENDCLASS."),
    )

    assert parent_lock_calls == []
    assert include_lock_calls == [("A4H", "ZCL_TEST")]


def _configure_mutation(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(testclasses, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(testclasses, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(testclasses, "get_session", lambda system_id: session)
    monkeypatch.setattr(testclasses, "call_class_lock", lambda system_id, name: _lock_response())
    monkeypatch.setattr(testclasses, "call_class_unlock", lambda system_id, name, lock_handle: None)
    monkeypatch.setattr(testclasses, "call_class_testclasses_lock", lambda system_id, name: _lock_response())
    monkeypatch.setattr(testclasses, "call_class_testclasses_unlock", lambda system_id, name, lock_handle: None)
    return session


@pytest.mark.parametrize(
    ("method", "call_mutation"),
    [
        (
            "post",
            lambda transport: testclasses.call_class_testclasses_create("A4H", "ZCL_TEST", transport),
        ),
        (
            "put",
            lambda transport: testclasses.call_class_testclasses_update(
                "A4H",
                "ZCL_TEST",
                testclasses.ClassTestclassesUpdateRequest(source="CLASS ltc_test DEFINITION FOR TESTING. ENDCLASS."),
                transport,
            ),
        ),
    ],
)
def test_testclasses_mutation_sends_transport_as_corrnr_query_param(monkeypatch, method, call_mutation):
    session = _configure_mutation(monkeypatch)

    call_mutation(" A4HK900123 ")

    assert len(session.calls) == 1
    actual_method, url, kwargs = session.calls[0]
    assert actual_method == method
    assert "lockHandle" not in url
    assert "corrNr" not in url
    assert kwargs["params"] == {"lockHandle": "LOCK HANDLE", "corrNr": "A4HK900123"}
    assert "X-sap-adt-corrnr" not in kwargs["headers"]


@pytest.mark.parametrize(
    "call_mutation",
    [
        lambda transport: testclasses.call_class_testclasses_create("A4H", "ZCL_TEST", transport),
        lambda transport: testclasses.call_class_testclasses_update(
            "A4H",
            "ZCL_TEST",
            testclasses.ClassTestclassesUpdateRequest(source="CLASS ltc_test DEFINITION FOR TESTING. ENDCLASS."),
            transport,
        ),
    ],
)
def test_testclasses_mutation_omits_corrnr_when_transport_is_empty(monkeypatch, call_mutation):
    session = _configure_mutation(monkeypatch)

    call_mutation("   ")

    assert session.calls[0][2]["params"] == {"lockHandle": "LOCK HANDLE"}


def test_testclasses_write_from_file_forwards_transport(monkeypatch, tmp_path):
    source_file = tmp_path / "testclasses.abap"
    source_file.write_text("CLASS ltc_test DEFINITION FOR TESTING. ENDCLASS.", encoding="utf-8")
    captured = []

    def fake_update(system_id, class_name, request, transport_number):
        captured.append((system_id, class_name, request.source, transport_number))
        return SimpleNamespace(
            result=True,
            data=SimpleNamespace(sourceUri="/source", contentType="text/plain"),
            message="",
            httpCode=200,
            httpReason="OK",
        )

    monkeypatch.setattr(testclasses, "call_class_testclasses_update", fake_update)

    response = testclasses.call_class_testclasses_write_from_file(
        "A4H",
        "ZCL_TEST",
        str(source_file),
        "A4HK900123",
    )

    assert response.result is True
    assert captured == [(
        "A4H",
        "ZCL_TEST",
        "CLASS ltc_test DEFINITION FOR TESTING. ENDCLASS.",
        "A4HK900123",
    )]
