from types import SimpleNamespace

import pytest

from abapunit import abapunit


# region Helpers

def test_ensure_list_returns_empty_for_none():
    assert abapunit._ensure_list(None) == []


def test_ensure_list_wraps_single_item():
    assert abapunit._ensure_list({"a": 1}) == [{"a": 1}]


def test_ensure_list_passes_through_list():
    assert abapunit._ensure_list([1, 2, 3]) == [1, 2, 3]


def test_find_link_href_returns_matching_href():
    links = [
        {"@rel": "http://www.sap.com/adt/relations/runtime/traces/coverage/results/bulkstatements", "@href": "/sap/bc/adt/runtime/traces/coverage/measurements/42/statements"},
        {"@rel": "http://www.sap.com/adt/relations/other", "@href": "/other"},
    ]
    result = abapunit._find_link_href(links, "bulkstatements")
    assert result == "/sap/bc/adt/runtime/traces/coverage/measurements/42/statements"


def test_find_link_href_returns_empty_when_no_match():
    links = [{"@rel": "http://www.sap.com/adt/relations/other", "@href": "/other"}]
    assert abapunit._find_link_href(links, "bulkstatements") == ""


def test_find_link_href_handles_empty_list():
    assert abapunit._find_link_href([], "bulkstatements") == ""

# endregion


# region Tool 1 — _build_abapunit_run_payload

def test_build_abapunit_run_payload_includes_object_uri():
    payload = abapunit._build_abapunit_run_payload(
        ["/sap/bc/adt/oo/classes/zcl_my_class"], withCoverage=True
    )
    assert 'adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class"' in payload


def test_build_abapunit_run_payload_coverage_active_true():
    payload = abapunit._build_abapunit_run_payload(
        ["/sap/bc/adt/oo/classes/zcl_my_class"], withCoverage=True
    )
    assert 'active="true"' in payload


def test_build_abapunit_run_payload_coverage_active_false():
    payload = abapunit._build_abapunit_run_payload(
        ["/sap/bc/adt/oo/classes/zcl_my_class"], withCoverage=False
    )
    assert 'active="false"' in payload


def test_build_abapunit_run_payload_includes_multiple_uris():
    payload = abapunit._build_abapunit_run_payload(
        ["/sap/bc/adt/oo/classes/zcl_a", "/sap/bc/adt/oo/classes/zcl_b"],
        withCoverage=False,
    )
    assert 'adtcore:uri="/sap/bc/adt/oo/classes/zcl_a"' in payload
    assert 'adtcore:uri="/sap/bc/adt/oo/classes/zcl_b"' in payload


def test_build_abapunit_run_payload_uses_aunit_namespace():
    payload = abapunit._build_abapunit_run_payload(
        ["/sap/bc/adt/oo/classes/zcl_my_class"], withCoverage=True
    )
    assert 'xmlns:aunit="http://www.sap.com/adt/aunit"' in payload
    assert "aunit:runConfiguration" in payload

# endregion


# region Tool 1 — _parse_abapunit_run_response

_RUN_RESPONSE_PASS_XML = """<?xml version="1.0" encoding="utf-8"?>
<aunit:runResult xmlns:aunit="http://www.sap.com/adt/aunit" xmlns:adtcore="http://www.sap.com/adt/core">
  <external>
    <coverage adtcore:uri="/sap/bc/adt/runtime/traces/coverage/measurements/99"/>
  </external>
  <program adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class" adtcore:name="ZCL_MY_CLASS" adtcore:type="CLAS/OC">
    <testClasses>
      <testClass adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/testclasses" adtcore:name="ZCL_MY_CLASS_TEST" durationCategory="short" riskLevel="harmless">
        <testMethods>
          <testMethod adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/testclasses#method=test_add" adtcore:name="TEST_ADD" executionTime="0.001"/>
        </testMethods>
      </testClass>
    </testClasses>
  </program>
</aunit:runResult>"""

_RUN_RESPONSE_FAIL_XML = """<?xml version="1.0" encoding="utf-8"?>
<aunit:runResult xmlns:aunit="http://www.sap.com/adt/aunit" xmlns:adtcore="http://www.sap.com/adt/core">
  <external>
    <coverage adtcore:uri=""/>
  </external>
  <program adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class" adtcore:name="ZCL_MY_CLASS" adtcore:type="CLAS/OC">
    <testClasses>
      <testClass adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/testclasses" adtcore:name="ZCL_MY_CLASS_TEST" durationCategory="short" riskLevel="harmless">
        <testMethods>
          <testMethod adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/testclasses#method=test_add" adtcore:name="TEST_ADD" executionTime="0.002">
            <alerts>
              <alert kind="failedAssertion" severity="critical">
                <title>Assertion failed</title>
                <details>Expected 5 but got 4</details>
              </alert>
            </alerts>
          </testMethod>
        </testMethods>
      </testClass>
    </testClasses>
  </program>
</aunit:runResult>"""


def test_parse_abapunit_run_response_all_passed():
    response = SimpleNamespace(text=_RUN_RESPONSE_PASS_XML)
    output = abapunit._parse_abapunit_run_response(response)

    assert output.passed is True
    assert output.totalTests == 1
    assert output.passedTests == 1
    assert output.failedTests == 0


def test_parse_abapunit_run_response_extracts_coverage_uri():
    response = SimpleNamespace(text=_RUN_RESPONSE_PASS_XML)
    output = abapunit._parse_abapunit_run_response(response)

    assert output.coverageMeasurementUri == "/sap/bc/adt/runtime/traces/coverage/measurements/99"


def test_parse_abapunit_run_response_failed_test_with_alert():
    response = SimpleNamespace(text=_RUN_RESPONSE_FAIL_XML)
    output = abapunit._parse_abapunit_run_response(response)

    assert output.passed is False
    assert output.totalTests == 1
    assert output.failedTests == 1
    method = output.programs[0].testClasses[0].testMethods[0]
    assert method.passed is False
    assert len(method.alerts) == 1
    assert method.alerts[0].kind == "failedAssertion"
    assert method.alerts[0].severity == "critical"
    assert method.alerts[0].title == "Assertion failed"


def test_parse_abapunit_run_response_program_metadata():
    response = SimpleNamespace(text=_RUN_RESPONSE_PASS_XML)
    output = abapunit._parse_abapunit_run_response(response)

    assert len(output.programs) == 1
    prog = output.programs[0]
    assert prog.name == "ZCL_MY_CLASS"
    assert prog.objectType == "CLAS/OC"


def test_parse_abapunit_run_response_empty_result():
    xml = """<?xml version="1.0"?>
<aunit:runResult xmlns:aunit="http://www.sap.com/adt/aunit"/>"""
    response = SimpleNamespace(text=xml)
    output = abapunit._parse_abapunit_run_response(response)

    assert output.totalTests == 0
    assert output.passed is True
    assert output.programs == []
    assert output.coverageMeasurementUri == ""

# endregion


# region Tool 1 — call_abapunit_run validation

def test_call_abapunit_run_returns_400_for_empty_object_uris(monkeypatch):
    monkeypatch.setattr(abapunit, "ensure_login", lambda system_id: (True, ""))

    result = abapunit.call_abapunit_run("A4H", [])

    assert result.result is False
    assert result.httpCode == 400


def test_call_abapunit_run_returns_401_when_not_logged_in(monkeypatch):
    monkeypatch.setattr(
        abapunit, "ensure_login",
        lambda system_id: (False, "No active session.")
    )

    result = abapunit.call_abapunit_run("A4H", ["/sap/bc/adt/oo/classes/zcl_x"])

    assert result.result is False
    assert result.httpCode == 401

# endregion


# region Tool 2 — _build_coverage_query_payload

def test_build_coverage_query_payload_includes_object_uri():
    payload = abapunit._build_coverage_query_payload(["/sap/bc/adt/oo/classes/zcl_my_class"])
    assert 'adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class"' in payload


def test_build_coverage_query_payload_uses_cov_namespace():
    payload = abapunit._build_coverage_query_payload(["/sap/bc/adt/oo/classes/zcl_my_class"])
    assert 'xmlns:cov="http://www.sap.com/adt/cov"' in payload
    assert "cov:query" in payload

# endregion


# region Tool 2 — _parse_coverages

def test_parse_coverages_calculates_percentage():
    raw = {"coverage": [{"@type": "statement", "@total": "10", "@executed": "7"}]}
    coverages = abapunit._parse_coverages(raw)

    assert len(coverages) == 1
    assert coverages[0].type == "statement"
    assert coverages[0].total == 10
    assert coverages[0].executed == 7
    assert coverages[0].percentage == 70.0


def test_parse_coverages_zero_total_returns_zero_percentage():
    raw = {"coverage": [{"@type": "branch", "@total": "0", "@executed": "0"}]}
    coverages = abapunit._parse_coverages(raw)

    assert coverages[0].percentage == 0.0


def test_parse_coverages_empty_returns_empty_list():
    assert abapunit._parse_coverages(None) == []
    assert abapunit._parse_coverages({}) == []

# endregion


# region Tool 2 — _parse_coverage_query_response

_COVERAGE_QUERY_XML = """<?xml version="1.0" encoding="utf-8"?>
<cov:result xmlns:cov="http://www.sap.com/adt/cov" xmlns:adtcore="http://www.sap.com/adt/core" xmlns:atom="http://www.w3.org/2005/Atom">
  <atom:link rel="http://www.sap.com/adt/relations/runtime/traces/coverage/results/bulkstatements" href="/sap/bc/adt/runtime/traces/coverage/measurements/99/statements"/>
  <nodes>
    <node>
      <nodes>
        <node>
          <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main" adtcore:name="ZCL_MY_CLASS" adtcore:type="CLAS/OCI"/>
          <atom:link rel="http://www.sap.com/adt/relations/runtime/traces/coverage/results/statements" href="/sap/bc/adt/runtime/traces/coverage/measurements/99/statements/ZCL_MY_CLASS"/>
          <coverages>
            <coverage type="statement" total="20" executed="15"/>
          </coverages>
          <nodes>
            <node>
              <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=10,1" adtcore:name="APPLY_TAX" adtcore:type="CLAS/OM"/>
              <coverages>
                <coverage type="statement" total="5" executed="5"/>
              </coverages>
            </node>
          </nodes>
        </node>
      </nodes>
    </node>
  </nodes>
</cov:result>"""


def test_parse_coverage_query_response_extracts_bulk_uri():
    response = SimpleNamespace(text=_COVERAGE_QUERY_XML)
    output = abapunit._parse_coverage_query_response(response)

    assert output.statementsBulkUri == "/sap/bc/adt/runtime/traces/coverage/measurements/99/statements"


def test_parse_coverage_query_response_extracts_class():
    response = SimpleNamespace(text=_COVERAGE_QUERY_XML)
    output = abapunit._parse_coverage_query_response(response)

    assert len(output.classes) == 1
    cls = output.classes[0]
    assert cls.name == "ZCL_MY_CLASS"
    assert cls.objectType == "CLAS/OCI"


def test_parse_coverage_query_response_extracts_method():
    response = SimpleNamespace(text=_COVERAGE_QUERY_XML)
    output = abapunit._parse_coverage_query_response(response)

    cls = output.classes[0]
    assert len(cls.methods) == 1
    assert cls.methods[0].name == "APPLY_TAX"


def test_parse_coverage_query_response_statements_request_path():
    response = SimpleNamespace(text=_COVERAGE_QUERY_XML)
    output = abapunit._parse_coverage_query_response(response)

    assert output.statementsRequestPaths == [
        "/sap/bc/adt/runtime/traces/coverage/measurements/99/statements/ZCL_MY_CLASS"
    ]
    assert output.classes[0].statementsRequestPath == (
        "/sap/bc/adt/runtime/traces/coverage/measurements/99/statements/ZCL_MY_CLASS"
    )


def test_parse_coverage_query_response_coverage_percentage():
    response = SimpleNamespace(text=_COVERAGE_QUERY_XML)
    output = abapunit._parse_coverage_query_response(response)

    cov = output.classes[0].coverages[0]
    assert cov.type == "statement"
    assert cov.total == 20
    assert cov.executed == 15
    assert cov.percentage == 75.0

# endregion


# region Tool 2 — call_abapunit_coverage_query validation

def test_call_abapunit_coverage_query_returns_400_for_empty_measurement_uri(monkeypatch):
    monkeypatch.setattr(abapunit, "ensure_login", lambda system_id: (True, ""))

    result = abapunit.call_abapunit_coverage_query("A4H", "", ["/sap/bc/adt/oo/classes/zcl_x"])

    assert result.result is False
    assert result.httpCode == 400


def test_call_abapunit_coverage_query_returns_400_for_empty_object_uris(monkeypatch):
    monkeypatch.setattr(abapunit, "ensure_login", lambda system_id: (True, ""))

    result = abapunit.call_abapunit_coverage_query(
        "A4H",
        "/sap/bc/adt/runtime/traces/coverage/measurements/99",
        [],
    )

    assert result.result is False
    assert result.httpCode == 400

# endregion


# region Tool 3 — _build_coverage_statements_payload

def test_build_coverage_statements_payload_includes_paths():
    payload = abapunit._build_coverage_statements_payload([
        "/sap/bc/adt/runtime/traces/coverage/measurements/99/statements/ZCL_MY_CLASS",
    ])
    assert "ZCL_MY_CLASS" in payload
    assert "statementsRequest" in payload


def test_build_coverage_statements_payload_uses_cov_namespace():
    payload = abapunit._build_coverage_statements_payload(["/path/to/statements/X"])
    assert 'xmlns:cov="http://www.sap.com/adt/cov"' in payload
    assert "cov:statementsBulkRequest" in payload

# endregion


# region Tool 3 — _parse_coverage_statements_response

_STATEMENTS_XML = """<?xml version="1.0" encoding="utf-8"?>
<cov:statementsBulkResponse xmlns:cov="http://www.sap.com/adt/cov" xmlns:adtcore="http://www.sap.com/adt/core" xmlns:atom="http://www.w3.org/2005/Atom">
  <cov:statementsResponse name="ZCL_MY_CLASS===============CP.ZCL_MY_CLASS.APPLY_TAX">
    <atom:link rel="http://www.sap.com/adt/relations/source" href="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=10,1"/>
    <procedure adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=10,1" executed="1">
      <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=10,1"/>
    </procedure>
    <statement executed="3" adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=11,1;end=11,30">
      <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=11,1;end=11,30"/>
    </statement>
    <statement executed="0" adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=12,1;end=12,20">
      <adtcore:objectReference adtcore:uri="/sap/bc/adt/oo/classes/zcl_my_class/source/main#start=12,1;end=12,20"/>
      <branch kind="conditional" executedTrue="3" executedFalse="0"/>
    </statement>
  </cov:statementsResponse>
</cov:statementsBulkResponse>"""


def test_parse_coverage_statements_response_extracts_method_name():
    response = SimpleNamespace(text=_STATEMENTS_XML)
    output = abapunit._parse_coverage_statements_response(response)

    assert len(output.methods) == 1
    assert output.methods[0].name == "ZCL_MY_CLASS===============CP.ZCL_MY_CLASS.APPLY_TAX"


def test_parse_coverage_statements_response_extracts_source_uri():
    response = SimpleNamespace(text=_STATEMENTS_XML)
    output = abapunit._parse_coverage_statements_response(response)

    assert "/source/main#start=10,1" in output.methods[0].sourceUri


def test_parse_coverage_statements_response_statements_include_procedure():
    response = SimpleNamespace(text=_STATEMENTS_XML)
    output = abapunit._parse_coverage_statements_response(response)

    stmts = output.methods[0].statements
    assert len(stmts) == 3  # 1 procedure + 2 statements


def test_parse_coverage_statements_response_unexecuted_statement():
    response = SimpleNamespace(text=_STATEMENTS_XML)
    output = abapunit._parse_coverage_statements_response(response)

    stmts = output.methods[0].statements
    unexecuted = [s for s in stmts if s.executed == 0]
    assert len(unexecuted) == 1
    assert "start=12" in unexecuted[0].sourceUri


def test_parse_coverage_statements_response_branch_detail():
    response = SimpleNamespace(text=_STATEMENTS_XML)
    output = abapunit._parse_coverage_statements_response(response)

    stmts = output.methods[0].statements
    branched = [s for s in stmts if s.branches]
    assert len(branched) == 1
    branch = branched[0].branches[0]
    assert branch.kind == "conditional"
    assert branch.executedTrue == 3
    assert branch.executedFalse == 0

# endregion


# region Tool 3 — call_abapunit_coverage_statements validation

def test_call_abapunit_coverage_statements_returns_400_for_empty_paths(monkeypatch):
    monkeypatch.setattr(abapunit, "ensure_login", lambda system_id: (True, ""))

    result = abapunit.call_abapunit_coverage_statements("A4H", [])

    assert result.result is False
    assert result.httpCode == 400


def test_call_abapunit_coverage_statements_returns_400_for_invalid_path_format(monkeypatch):
    monkeypatch.setattr(abapunit, "ensure_login", lambda system_id: (True, ""))

    result = abapunit.call_abapunit_coverage_statements("A4H", ["/sap/bc/adt/no_marker_here"])

    assert result.result is False
    assert result.httpCode == 400
    assert "/statements/" in result.message


def test_call_abapunit_coverage_statements_derives_bulk_uri_correctly(monkeypatch):
    monkeypatch.setattr(abapunit, "ensure_login", lambda system_id: (True, ""))

    captured = []

    class FakeSession:
        def post(self, url, **kwargs):
            captured.append(url)
            return SimpleNamespace(status_code=200, reason="OK", text=_STATEMENTS_XML)

    from types import SimpleNamespace as SN
    fake_config = SN(server="https://fake:8443")
    monkeypatch.setattr(abapunit, "get_system_config", lambda system_id: fake_config)
    monkeypatch.setattr(abapunit, "get_session", lambda system_id: FakeSession())

    abapunit.call_abapunit_coverage_statements(
        "A4H",
        ["/sap/bc/adt/runtime/traces/coverage/measurements/99/statements/ZCL_MY_CLASS"],
    )

    assert captured == ["https://fake:8443/sap/bc/adt/runtime/traces/coverage/measurements/99/statements"]

# endregion
