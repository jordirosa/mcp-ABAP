from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from connection.connection import ensure_login
from generics import ApiResponse


ABAPUNIT_TESTRUNS_URI = "/sap/bc/adt/abapunit/testruns"
ABAPUNIT_COVERAGE_BULKSTATEMENTS_REL = "http://www.sap.com/adt/relations/runtime/traces/coverage/results/bulkstatements"
ABAPUNIT_COVERAGE_STATEMENTS_REL = "http://www.sap.com/adt/relations/runtime/traces/coverage/results/statements"


# region Helpers

def _ensure_list(val) -> list:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _find_link_href(links, rel_contains: str) -> str:
    for link in _ensure_list(links):
        if rel_contains in (link.get("@rel", "") or ""):
            return link.get("@href", "") or ""
    return ""

# endregion


# region Tool 1 — Test Run

class AbapUnitAlertOutput(BaseModel):
    """A failure or error reported for one ABAP Unit test method."""

    kind: str = Field(..., description="Alert category returned by SAP, e.g. 'failedAssertion' or 'exception'.")
    severity: str = Field(..., description="Severity level: 'critical', 'tolerable' or 'harmless'.")
    title: str = Field("", description="Short description of the failure.")
    details: str = Field("", description="Extended stack trace or assertion details.")


class AbapUnitTestMethodOutput(BaseModel):
    """Execution result for one ABAP Unit test method."""

    uri: str = Field(..., description="ADT URI of the test method, including class and method name fragments.")
    name: str = Field(..., description="Technical name of the test method.")
    executionTime: float = Field(..., description="Wall-clock execution time in seconds.")
    passed: bool = Field(..., description="True when the method produced no alerts.")
    alerts: list[AbapUnitAlertOutput] = Field(
        default_factory=list,
        description="Failures or errors raised during execution. Empty list means the method passed."
    )


class AbapUnitTestClassOutput(BaseModel):
    """Execution results for one ABAP Unit test class."""

    uri: str = Field(..., description="ADT URI of the test class.")
    name: str = Field(..., description="Technical name of the test class.")
    durationCategory: str = Field("", description="Duration category declared on the class: 'short', 'medium' or 'long'.")
    riskLevel: str = Field("", description="Risk level declared on the class: 'harmless', 'dangerous' or 'critical'.")
    passed: bool = Field(..., description="True when every test method in this class passed.")
    testMethods: list[AbapUnitTestMethodOutput] = Field(
        default_factory=list,
        description="Individual test method results inside this class."
    )


class AbapUnitProgramOutput(BaseModel):
    """Test results grouped by the ABAP program or class under test."""

    uri: str = Field(..., description="ADT URI of the program or class under test.")
    name: str = Field(..., description="Technical name of the program or class under test.")
    objectType: str = Field("", description="ADT object type, e.g. 'CLAS/OC' or 'PROG/P'.")
    testClasses: list[AbapUnitTestClassOutput] = Field(
        default_factory=list,
        description="All test classes found and executed for this program."
    )


class AbapUnitRunOutput(BaseModel):
    """Aggregated result of one ABAP Unit test run."""

    programs: list[AbapUnitProgramOutput] = Field(
        default_factory=list,
        description="Test results grouped by program or class under test."
    )
    totalTests: int = Field(..., description="Total number of test methods executed.")
    passedTests: int = Field(..., description="Number of test methods that passed.")
    failedTests: int = Field(..., description="Number of test methods that failed or raised errors.")
    passed: bool = Field(..., description="True when every test method in the run passed.")
    coverageMeasurementUri: str = Field(
        "",
        description=(
            "ADT URI of the coverage measurement created during this run, "
            "e.g. '/sap/bc/adt/runtime/traces/coverage/measurements/{id}'. "
            "Pass this value to abapunit_coverage_query to retrieve coverage data. "
            "Empty when withCoverage was False."
        )
    )


class AbapUnitRunResponse(ApiResponse[AbapUnitRunOutput]):
    """Response returned by the ABAP Unit test runner tool."""


def _build_abapunit_run_payload(objectUris: list[str], withCoverage: bool) -> str:
    refs = [{"@adtcore:uri": uri} for uri in objectUris]
    payload = {
        "aunit:runConfiguration": {
            "@xmlns:aunit": "http://www.sap.com/adt/aunit",
            "external": {
                "coverage": {"@active": "true" if withCoverage else "false"}
            },
            "options": {
                "uriType": {"@value": "semantic"},
                "testDeterminationStrategy": {
                    "@sameProgram": "true",
                    "@assignedTests": "false",
                    "@appendAssignedTestsPreview": "true",
                },
                "testRiskLevels": {"@harmless": "true", "@dangerous": "true", "@critical": "true"},
                "testDurations": {"@short": "true", "@medium": "true", "@long": "true"},
                "withNavigationUri": {"@enabled": "false"},
            },
            "adtcore:objectSets": {
                "@xmlns:adtcore": "http://www.sap.com/adt/core",
                "objectSet": {
                    "@kind": "inclusive",
                    "adtcore:objectReferences": {
                        "adtcore:objectReference": refs
                    },
                },
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def _parse_abapunit_run_response(response) -> AbapUnitRunOutput:
    parsed = xmltodict.parse(response.text, force_list=("program", "testClass", "testMethod", "alert", "atom:link"))
    root = parsed.get("aunit:runResult", {}) or {}

    external = root.get("external", {}) or {}
    coverage_elem = (external.get("coverage", {}) or {})
    coverage_uri = coverage_elem.get("@adtcore:uri", "") or ""

    total = 0
    failed = 0
    programs: list[AbapUnitProgramOutput] = []

    for prog in _ensure_list(root.get("program")):
        test_classes: list[AbapUnitTestClassOutput] = []
        raw_classes = _ensure_list((prog.get("testClasses", {}) or {}).get("testClass"))

        for tc in raw_classes:
            methods: list[AbapUnitTestMethodOutput] = []
            raw_methods = _ensure_list((tc.get("testMethods", {}) or {}).get("testMethod"))

            for tm in raw_methods:
                raw_alerts = _ensure_list((tm.get("alerts", {}) or {}).get("alert"))
                alerts = [
                    AbapUnitAlertOutput(
                        kind=a.get("@kind", ""),
                        severity=a.get("@severity", ""),
                        title=str(a.get("title", "") or ""),
                        details=str(a.get("details", "") or ""),
                    )
                    for a in raw_alerts
                ]
                method_passed = len(alerts) == 0
                total += 1
                if not method_passed:
                    failed += 1
                methods.append(AbapUnitTestMethodOutput(
                    uri=tm.get("@adtcore:uri", ""),
                    name=tm.get("@adtcore:name", ""),
                    executionTime=float(tm.get("@executionTime", 0) or 0),
                    passed=method_passed,
                    alerts=alerts,
                ))

            test_classes.append(AbapUnitTestClassOutput(
                uri=tc.get("@adtcore:uri", ""),
                name=tc.get("@adtcore:name", ""),
                durationCategory=tc.get("@durationCategory", ""),
                riskLevel=tc.get("@riskLevel", ""),
                passed=all(m.passed for m in methods),
                testMethods=methods,
            ))

        programs.append(AbapUnitProgramOutput(
            uri=prog.get("@adtcore:uri", ""),
            name=prog.get("@adtcore:name", ""),
            objectType=prog.get("@adtcore:type", ""),
            testClasses=test_classes,
        ))

    return AbapUnitRunOutput(
        programs=programs,
        totalTests=total,
        passedTests=total - failed,
        failedTests=failed,
        passed=failed == 0,
        coverageMeasurementUri=coverage_uri,
    )


def call_abapunit_run(
    systemId: str,
    objectUris: list[str],
    withCoverage: bool = True,
) -> AbapUnitRunResponse:
    """Execute ABAP Unit tests for one or more objects through the ADT test runner endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return AbapUnitRunResponse.model_validate({
                "result": False, "httpCode": 401, "httpReason": "Unauthorized",
                "message": f"Cannot run ABAP Unit tests because no SAP session is available: {error_msg}",
                "data": None,
            })

        if not objectUris:
            raise ValueError("objectUris must contain at least one ADT URI.")

        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.abapunit.testruns.config.v4+xml",
            "Accept": "application/vnd.sap.adt.abapunit.testruns.result.v2+xml",
        }
        payload = _build_abapunit_run_payload(objectUris, withCoverage)
        response = get_session(systemId).post(
            f"{system_config.server}{ABAPUNIT_TESTRUNS_URI}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return AbapUnitRunResponse.model_validate({
                "result": False, "httpCode": response.status_code, "httpReason": response.reason,
                "message": f"ADT rejected the ABAP Unit test run request: {response.text}",
                "data": None,
            })

        output = _parse_abapunit_run_response(response)
        status = "passed" if output.passed else f"{output.failedTests} failed"
        return AbapUnitRunResponse.model_validate({
            "result": True, "httpCode": response.status_code, "httpReason": response.reason,
            "message": f"ABAP Unit test run completed: {output.totalTests} tests, {status}.",
            "data": output,
        })
    except ValueError as exc:
        return AbapUnitRunResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": str(exc), "data": None,
        })
    except Exception as exc:
        return AbapUnitRunResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Unexpected error while running ABAP Unit tests: {str(exc)}", "data": None,
        })

# endregion


# region Tool 2 — Coverage Query

class AbapUnitCoverageTypeOutput(BaseModel):
    """Coverage counts for one measurement type."""

    type: str = Field(..., description="Measurement type: 'branch', 'procedure' or 'statement'.")
    total: int = Field(..., description="Total number of coverable items of this type.")
    executed: int = Field(..., description="Number of items that were executed during the test run.")
    percentage: float = Field(..., description="Coverage percentage (0–100). 100.0 means full coverage.")


class AbapUnitCoverageMethodOutput(BaseModel):
    """Coverage summary for one method or procedure."""

    uri: str = Field(..., description="ADT source URI of the method including start line, e.g. '.../source/main#start=55,9'.")
    name: str = Field(..., description="Technical name of the method.")
    objectType: str = Field("", description="ADT object type, e.g. 'CLAS/OM'.")
    coverages: list[AbapUnitCoverageTypeOutput] = Field(
        default_factory=list,
        description="Branch, procedure and statement coverage counts for this method."
    )


class AbapUnitCoverageClassOutput(BaseModel):
    """Coverage summary for one class implementation."""

    uri: str = Field(..., description="ADT source URI of the class implementation.")
    name: str = Field(..., description="Technical name of the class implementation.")
    objectType: str = Field("", description="ADT object type, e.g. 'CLAS/OCI'.")
    coverages: list[AbapUnitCoverageTypeOutput] = Field(
        default_factory=list,
        description="Aggregated branch, procedure and statement coverage for the whole class."
    )
    methods: list[AbapUnitCoverageMethodOutput] = Field(
        default_factory=list,
        description="Per-method coverage breakdown."
    )
    statementsRequestPath: str = Field(
        "",
        description=(
            "Full URI to request statement-level detail for this class via abapunit_coverage_statements. "
            "Include this value in the statementsRequestPaths list."
        )
    )


class AbapUnitCoverageQueryOutput(BaseModel):
    """Coverage summary for the requested object set after a test run."""

    statementsBulkUri: str = Field(
        ...,
        description=(
            "ADT URI of the bulk statements endpoint, "
            "e.g. '/sap/bc/adt/runtime/traces/coverage/results/{id}/statements'. "
            "This is derived from the coverage results and used internally by abapunit_coverage_statements."
        )
    )
    classes: list[AbapUnitCoverageClassOutput] = Field(
        default_factory=list,
        description="Coverage breakdown per class and method."
    )
    statementsRequestPaths: list[str] = Field(
        default_factory=list,
        description=(
            "All statement path URIs for every class in the result set. "
            "Pass this list directly to abapunit_coverage_statements to retrieve "
            "full line-level coverage for all methods in one call."
        )
    )


class AbapUnitCoverageQueryResponse(ApiResponse[AbapUnitCoverageQueryOutput]):
    """Response returned by the coverage summary query tool."""


def _parse_coverages(coverages_raw) -> list[AbapUnitCoverageTypeOutput]:
    result = []
    for c in _ensure_list((coverages_raw or {}).get("coverage")):
        total = int(c.get("@total", 0) or 0)
        executed = int(c.get("@executed", 0) or 0)
        pct = round(executed / total * 100, 1) if total > 0 else 0.0
        result.append(AbapUnitCoverageTypeOutput(
            type=c.get("@type", ""),
            total=total,
            executed=executed,
            percentage=pct,
        ))
    return result


def _build_coverage_query_payload(objectUris: list[str]) -> str:
    refs = [{"@adtcore:uri": uri} for uri in objectUris]
    payload = {
        "cov:query": {
            "@xmlns:cov": "http://www.sap.com/adt/cov",
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "adtcore:objectSets": {
                "@xmlns:adtcore": "http://www.sap.com/adt/core",
                "objectSet": {
                    "@kind": "inclusive",
                    "adtcore:objectReferences": {
                        "adtcore:objectReference": refs
                    },
                },
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def _parse_coverage_query_response(response) -> AbapUnitCoverageQueryOutput:
    parsed = xmltodict.parse(
        response.text,
        force_list=("atom:link", "node", "coverage"),
    )
    root = parsed.get("cov:result", {}) or {}

    root_links = _ensure_list(root.get("atom:link"))
    statements_bulk_uri = _find_link_href(root_links, "bulkstatements")

    classes: list[AbapUnitCoverageClassOutput] = []
    statements_request_paths: list[str] = []

    top_nodes = _ensure_list((root.get("nodes", {}) or {}).get("node"))
    for top_node in top_nodes:
        inner_nodes = _ensure_list((top_node.get("nodes", {}) or {}).get("node"))
        for impl_node in inner_nodes:
            obj_ref = impl_node.get("adtcore:objectReference", {}) or {}
            impl_links = _ensure_list(impl_node.get("atom:link"))
            statements_path = _find_link_href(impl_links, "results/statements")
            if statements_path:
                statements_request_paths.append(statements_path)

            method_nodes = _ensure_list((impl_node.get("nodes", {}) or {}).get("node"))
            methods: list[AbapUnitCoverageMethodOutput] = []
            for method_node in method_nodes:
                m_ref = method_node.get("adtcore:objectReference", {}) or {}
                methods.append(AbapUnitCoverageMethodOutput(
                    uri=m_ref.get("@adtcore:uri", ""),
                    name=m_ref.get("@adtcore:name", ""),
                    objectType=m_ref.get("@adtcore:type", ""),
                    coverages=_parse_coverages(method_node.get("coverages")),
                ))

            classes.append(AbapUnitCoverageClassOutput(
                uri=obj_ref.get("@adtcore:uri", ""),
                name=obj_ref.get("@adtcore:name", ""),
                objectType=obj_ref.get("@adtcore:type", ""),
                coverages=_parse_coverages(impl_node.get("coverages")),
                methods=methods,
                statementsRequestPath=statements_path,
            ))

    return AbapUnitCoverageQueryOutput(
        statementsBulkUri=statements_bulk_uri,
        classes=classes,
        statementsRequestPaths=statements_request_paths,
    )


def call_abapunit_coverage_query(
    systemId: str,
    measurementUri: str,
    objectUris: list[str],
) -> AbapUnitCoverageQueryResponse:
    """Query code coverage summary from one measurement produced by a test run."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return AbapUnitCoverageQueryResponse.model_validate({
                "result": False, "httpCode": 401, "httpReason": "Unauthorized",
                "message": f"Cannot query coverage because no SAP session is available: {error_msg}",
                "data": None,
            })

        if not measurementUri:
            raise ValueError("measurementUri is required.")
        if not objectUris:
            raise ValueError("objectUris must contain at least one ADT URI.")

        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/xml",
            "Accept": "application/vnd.sap.adt.coverage.measurements.v1+xml, application/xml",
        }
        payload = _build_coverage_query_payload(objectUris)
        response = get_session(systemId).post(
            f"{system_config.server}{measurementUri}?withAdditionalTypeInfo=true",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return AbapUnitCoverageQueryResponse.model_validate({
                "result": False, "httpCode": response.status_code, "httpReason": response.reason,
                "message": f"ADT rejected the coverage query request: {response.text}",
                "data": None,
            })

        output = _parse_coverage_query_response(response)
        return AbapUnitCoverageQueryResponse.model_validate({
            "result": True, "httpCode": response.status_code, "httpReason": response.reason,
            "message": f"Coverage summary retrieved for {len(output.classes)} class(es).",
            "data": output,
        })
    except ValueError as exc:
        return AbapUnitCoverageQueryResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": str(exc), "data": None,
        })
    except Exception as exc:
        return AbapUnitCoverageQueryResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Unexpected error while querying coverage: {str(exc)}", "data": None,
        })

# endregion


# region Tool 3 — Coverage Statements

class AbapUnitCoverageBranchOutput(BaseModel):
    """Execution counts for one conditional branch."""

    kind: str = Field(..., description="Branch type returned by SAP, typically 'conditional'.")
    executedTrue: int = Field(..., description="Number of times the true path was taken.")
    executedFalse: int = Field(..., description="Number of times the false path was taken.")


class AbapUnitCoverageStatementOutput(BaseModel):
    """Execution data for one source statement."""

    sourceUri: str = Field(
        ...,
        description=(
            "ADT source URI with start/end positions, "
            "e.g. '.../source/main#start=56,1;end=56,23'. "
            "Correlate line numbers against the class source to locate uncovered code."
        )
    )
    executed: int = Field(
        ...,
        description="Number of times this statement was executed. 0 means the statement was never reached."
    )
    branches: list[AbapUnitCoverageBranchOutput] = Field(
        default_factory=list,
        description="Branch coverage detail for conditional statements such as IF or CASE."
    )


class AbapUnitCoverageMethodStatementsOutput(BaseModel):
    """Line-level coverage data for one method."""

    name: str = Field(..., description="Fully qualified method name in SAP internal format, e.g. 'YJRS_TEST_CLASS===============CP.YJRS_TEST_CLASS.APPLY_TAX'.")
    sourceUri: str = Field("", description="ADT source URI pointing to the first line of the method.")
    statements: list[AbapUnitCoverageStatementOutput] = Field(
        default_factory=list,
        description="Execution counts per coverable statement in the method body, in source order."
    )


class AbapUnitCoverageStatementsOutput(BaseModel):
    """Line-level coverage data for all methods included in the bulk request."""

    methods: list[AbapUnitCoverageMethodStatementsOutput] = Field(
        default_factory=list,
        description=(
            "Per-method statement coverage results. "
            "Each method lists its statements with execution counts and branch directions. "
            "Statements with executed=0 identify uncovered lines."
        )
    )


class AbapUnitCoverageStatementsResponse(ApiResponse[AbapUnitCoverageStatementsOutput]):
    """Response returned by the coverage statements tool."""


def _build_coverage_statements_payload(statementsRequestPaths: list[str]) -> str:
    requests = [{"@get": path} for path in statementsRequestPaths]
    payload = {
        "cov:statementsBulkRequest": {
            "@xmlns:cov": "http://www.sap.com/adt/cov",
            "statementsRequest": requests,
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def _parse_coverage_statements_response(response) -> AbapUnitCoverageStatementsOutput:
    parsed = xmltodict.parse(
        response.text,
        force_list=("cov:statementsResponse", "statement", "procedure", "atom:link", "branch", "condition"),
    )
    root = parsed.get("cov:statementsBulkResponse", {}) or {}
    method_responses = _ensure_list(root.get("cov:statementsResponse"))

    methods: list[AbapUnitCoverageMethodStatementsOutput] = []
    for resp in method_responses:
        resp_links = _ensure_list(resp.get("atom:link"))
        source_uri = _find_link_href(resp_links, "adt/relations/source")

        statements: list[AbapUnitCoverageStatementOutput] = []

        # Procedures are treated as the first statement (entry point coverage)
        for proc in _ensure_list(resp.get("procedure")):
            obj_ref = (proc.get("adtcore:objectReference", {}) or {})
            statements.append(AbapUnitCoverageStatementOutput(
                sourceUri=obj_ref.get("@adtcore:uri", ""),
                executed=int(proc.get("@executed", 0) or 0),
            ))

        for stmt in _ensure_list(resp.get("statement")):
            obj_ref = (stmt.get("adtcore:objectReference", {}) or {})
            raw_branches = _ensure_list(stmt.get("branch"))
            branches = [
                AbapUnitCoverageBranchOutput(
                    kind=b.get("@kind", ""),
                    executedTrue=int(b.get("@executedTrue", 0) or 0),
                    executedFalse=int(b.get("@executedFalse", 0) or 0),
                )
                for b in raw_branches
            ]
            statements.append(AbapUnitCoverageStatementOutput(
                sourceUri=obj_ref.get("@adtcore:uri", ""),
                executed=int(stmt.get("@executed", 0) or 0),
                branches=branches,
            ))

        methods.append(AbapUnitCoverageMethodStatementsOutput(
            name=resp.get("@name", ""),
            sourceUri=source_uri,
            statements=statements,
        ))

    return AbapUnitCoverageStatementsOutput(methods=methods)


def call_abapunit_coverage_statements(
    systemId: str,
    statementsRequestPaths: list[str],
) -> AbapUnitCoverageStatementsResponse:
    """Retrieve line-level statement coverage for one or more methods via a bulk request."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return AbapUnitCoverageStatementsResponse.model_validate({
                "result": False, "httpCode": 401, "httpReason": "Unauthorized",
                "message": f"Cannot retrieve coverage statements because no SAP session is available: {error_msg}",
                "data": None,
            })

        if not statementsRequestPaths:
            raise ValueError("statementsRequestPaths must contain at least one path.")

        # Derive the bulk POST URI from the first path: keep everything up to and including /statements
        marker = "/statements/"
        first = statementsRequestPaths[0]
        idx = first.find(marker)
        if idx == -1:
            raise ValueError(
                f"statementsRequestPaths entries must contain '/statements/' — got: {first!r}. "
                "Use the statementsRequestPaths list returned by abapunit_coverage_query."
            )
        bulk_uri = first[: idx + len("/statements")]

        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/xml",
            "Accept": "application/xml",
        }
        payload = _build_coverage_statements_payload(statementsRequestPaths)
        response = get_session(systemId).post(
            f"{system_config.server}{bulk_uri}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return AbapUnitCoverageStatementsResponse.model_validate({
                "result": False, "httpCode": response.status_code, "httpReason": response.reason,
                "message": f"ADT rejected the coverage statements request: {response.text}",
                "data": None,
            })

        output = _parse_coverage_statements_response(response)
        return AbapUnitCoverageStatementsResponse.model_validate({
            "result": True, "httpCode": response.status_code, "httpReason": response.reason,
            "message": f"Statement coverage retrieved for {len(output.methods)} method(s).",
            "data": output,
        })
    except ValueError as exc:
        return AbapUnitCoverageStatementsResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": str(exc), "data": None,
        })
    except Exception as exc:
        return AbapUnitCoverageStatementsResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Unexpected error while retrieving coverage statements: {str(exc)}", "data": None,
        })

# endregion
