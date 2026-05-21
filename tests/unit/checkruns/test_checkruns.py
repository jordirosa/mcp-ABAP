import base64
from types import SimpleNamespace

from checkruns import checkruns


# region Helpers

def test_ensure_list_returns_empty_for_none():
    assert checkruns._ensure_list(None) == []


def test_ensure_list_wraps_single_item():
    assert checkruns._ensure_list({"a": 1}) == [{"a": 1}]


def test_ensure_list_passes_through_list():
    assert checkruns._ensure_list([1, 2]) == [1, 2]

# endregion


# region _build_checkrun_payload

def test_build_checkrun_payload_uses_chkrun_namespace():
    payload = checkruns._build_checkrun_payload(
        objectUri="/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001",
        sourceUri="/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001/source/main",
        source="define view entity YJRS_CDS_0001 as select from t000 { key mandt }",
        version="inactive",
    )
    assert 'xmlns:chkrun="http://www.sap.com/adt/checkrun"' in payload
    assert "chkrun:checkObjectList" in payload


def test_build_checkrun_payload_sets_object_uri_and_version():
    payload = checkruns._build_checkrun_payload(
        objectUri="/sap/bc/adt/oo/classes/zcl_my_class",
        sourceUri="/sap/bc/adt/oo/classes/zcl_my_class/source/main",
        source="CLASS zcl_my_class DEFINITION. ENDCLASS.",
        version="active",
    )
    assert 'adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class"' in payload
    assert 'chkrun:version="active"' in payload


def test_build_checkrun_payload_sets_source_uri_in_artifact():
    payload = checkruns._build_checkrun_payload(
        objectUri="/sap/bc/adt/oo/classes/zcl_my_class",
        sourceUri="/sap/bc/adt/oo/classes/zcl_my_class/source/main",
        source="some source",
        version="inactive",
    )
    assert 'chkrun:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main"' in payload


def test_build_checkrun_payload_base64_encodes_source():
    source = "define view entity TEST as select from t000 { key mandt }"
    payload = checkruns._build_checkrun_payload(
        objectUri="/sap/bc/adt/ddic/ddl/sources/test",
        sourceUri="/sap/bc/adt/ddic/ddl/sources/test/source/main",
        source=source,
        version="inactive",
    )
    expected_b64 = base64.b64encode(source.encode("utf-8")).decode("ascii")
    assert expected_b64 in payload


def test_build_checkrun_payload_default_version_is_inactive():
    payload = checkruns._build_checkrun_payload(
        objectUri="/sap/bc/adt/ddic/ddl/sources/test",
        sourceUri="/sap/bc/adt/ddic/ddl/sources/test/source/main",
        source="",
        version="inactive",
    )
    assert 'chkrun:version="inactive"' in payload

# endregion


# region _parse_checkrun_response

_RESPONSE_WITH_ERRORS_XML = """<?xml version="1.0" encoding="utf-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport
      chkrun:reporter="abapCheckRun"
      chkrun:triggeringUri="/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001"
      chkrun:status="processed"
      chkrun:statusText="Object YJRS_CDS_0001 has been checked">
    <chkrun:checkMessageList>
      <chkrun:checkMessage
          chkrun:uri="/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001/source/main#start=9,4"
          chkrun:type="E"
          chkrun:shortText="Syntax Errors">
        <chkrun:t100Key chkrun:msgid="SDDL_PARSER_MSG" chkrun:msgno="000"/>
      </chkrun:checkMessage>
    </chkrun:checkMessageList>
  </chkrun:checkReport>
</chkrun:checkRunReports>"""

_RESPONSE_WITH_WARNING_XML = """<?xml version="1.0" encoding="utf-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport
      chkrun:reporter="abapCheckRun"
      chkrun:triggeringUri="/sap/bc/adt/oo/classes/zcl_my_class"
      chkrun:status="processed"
      chkrun:statusText="Object ZCL_MY_CLASS has been checked">
    <chkrun:checkMessageList>
      <chkrun:checkMessage
          chkrun:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=5,1"
          chkrun:type="W"
          chkrun:shortText="Performance warning">
        <chkrun:t100Key chkrun:msgid="ABAP_PERF" chkrun:msgno="001"/>
      </chkrun:checkMessage>
    </chkrun:checkMessageList>
  </chkrun:checkReport>
</chkrun:checkRunReports>"""

_RESPONSE_CLEAN_XML = """<?xml version="1.0" encoding="utf-8"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun">
  <chkrun:checkReport
      chkrun:reporter="abapCheckRun"
      chkrun:triggeringUri="/sap/bc/adt/oo/classes/zcl_my_class"
      chkrun:status="processed"
      chkrun:statusText="Object ZCL_MY_CLASS has been checked">
    <chkrun:checkMessageList/>
  </chkrun:checkReport>
</chkrun:checkRunReports>"""


def test_parse_checkrun_response_error_sets_passed_false():
    response = SimpleNamespace(text=_RESPONSE_WITH_ERRORS_XML)
    output = checkruns._parse_checkrun_response(response)

    assert output.passed is False
    assert len(output.reports) == 1
    assert output.reports[0].hasErrors is True
    assert output.reports[0].hasWarnings is False


def test_parse_checkrun_response_error_message_details():
    response = SimpleNamespace(text=_RESPONSE_WITH_ERRORS_XML)
    output = checkruns._parse_checkrun_response(response)

    msg = output.reports[0].messages[0]
    assert msg.type == "E"
    assert msg.shortText == "Syntax Errors"
    assert msg.uri == "/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001/source/main#start=9,4"
    assert msg.msgId == "SDDL_PARSER_MSG"
    assert msg.msgNo == "000"


def test_parse_checkrun_response_warning_does_not_fail():
    response = SimpleNamespace(text=_RESPONSE_WITH_WARNING_XML)
    output = checkruns._parse_checkrun_response(response)

    assert output.passed is True
    assert output.reports[0].hasErrors is False
    assert output.reports[0].hasWarnings is True
    assert output.reports[0].messages[0].type == "W"


def test_parse_checkrun_response_clean_source_passes():
    response = SimpleNamespace(text=_RESPONSE_CLEAN_XML)
    output = checkruns._parse_checkrun_response(response)

    assert output.passed is True
    assert output.reports[0].messages == []
    assert output.reports[0].hasErrors is False
    assert output.reports[0].hasWarnings is False


def test_parse_checkrun_response_report_metadata():
    response = SimpleNamespace(text=_RESPONSE_WITH_ERRORS_XML)
    output = checkruns._parse_checkrun_response(response)

    report = output.reports[0]
    assert report.triggeringUri == "/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001"
    assert report.status == "processed"
    assert report.statusText == "Object YJRS_CDS_0001 has been checked"


def test_parse_checkrun_response_empty_reports():
    xml = """<?xml version="1.0"?>
<chkrun:checkRunReports xmlns:chkrun="http://www.sap.com/adt/checkrun"/>"""
    response = SimpleNamespace(text=xml)
    output = checkruns._parse_checkrun_response(response)

    assert output.passed is True
    assert output.reports == []

# endregion


# region call_checkrun validation

def test_call_checkrun_returns_401_when_not_logged_in(monkeypatch):
    monkeypatch.setattr(checkruns, "ensure_login", lambda system_id: (False, "No session."))

    result = checkruns.call_checkrun(
        "A4H",
        "/sap/bc/adt/oo/classes/zcl_x",
        "/sap/bc/adt/oo/classes/zcl_x/source/main",
        "source",
    )

    assert result.result is False
    assert result.httpCode == 401


def test_call_checkrun_returns_400_for_missing_object_uri(monkeypatch):
    monkeypatch.setattr(checkruns, "ensure_login", lambda system_id: (True, ""))

    result = checkruns.call_checkrun("A4H", "", "/sap/bc/adt/oo/classes/zcl_x/source/main", "source")

    assert result.result is False
    assert result.httpCode == 400


def test_call_checkrun_returns_400_for_missing_source_uri(monkeypatch):
    monkeypatch.setattr(checkruns, "ensure_login", lambda system_id: (True, ""))

    result = checkruns.call_checkrun("A4H", "/sap/bc/adt/oo/classes/zcl_x", "", "source")

    assert result.result is False
    assert result.httpCode == 400


def test_call_checkrun_posts_to_correct_url(monkeypatch):
    monkeypatch.setattr(checkruns, "ensure_login", lambda system_id: (True, ""))

    captured = []

    class FakeSession:
        def post(self, url, **kwargs):
            captured.append(url)
            return SimpleNamespace(status_code=200, reason="OK", text=_RESPONSE_CLEAN_XML)

    fake_config = SimpleNamespace(server="https://fake:8443")
    monkeypatch.setattr(checkruns, "get_system_config", lambda system_id: fake_config)
    monkeypatch.setattr(checkruns, "get_session", lambda system_id: FakeSession())

    checkruns.call_checkrun(
        "A4H",
        "/sap/bc/adt/oo/classes/zcl_x",
        "/sap/bc/adt/oo/classes/zcl_x/source/main",
        "source code",
    )

    assert captured == ["https://fake:8443/sap/bc/adt/checkruns?reporters=abapCheckRun"]


def test_call_checkrun_result_is_false_on_errors(monkeypatch):
    monkeypatch.setattr(checkruns, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(checkruns, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(
        checkruns, "get_session",
        lambda system_id: type("S", (), {"post": lambda self, url, **kw: SimpleNamespace(status_code=200, reason="OK", text=_RESPONSE_WITH_ERRORS_XML)})(),
    )

    result = checkruns.call_checkrun(
        "A4H",
        "/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001",
        "/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001/source/main",
        "bad source",
    )

    assert result.result is False
    assert result.data is not None
    assert result.data.passed is False
    assert "error" in result.message.lower()


def test_call_checkrun_result_is_true_on_clean_source(monkeypatch):
    monkeypatch.setattr(checkruns, "ensure_login", lambda system_id: (True, ""))
    monkeypatch.setattr(checkruns, "get_system_config", lambda system_id: SimpleNamespace(server="https://fake"))
    monkeypatch.setattr(
        checkruns, "get_session",
        lambda system_id: type("S", (), {"post": lambda self, url, **kw: SimpleNamespace(status_code=200, reason="OK", text=_RESPONSE_CLEAN_XML)})(),
    )

    result = checkruns.call_checkrun(
        "A4H",
        "/sap/bc/adt/oo/classes/zcl_my_class",
        "/sap/bc/adt/oo/classes/zcl_my_class/source/main",
        "CLASS zcl_my_class DEFINITION. ENDCLASS. CLASS zcl_my_class IMPLEMENTATION. ENDCLASS.",
    )

    assert result.result is True
    assert result.data.passed is True

# endregion
