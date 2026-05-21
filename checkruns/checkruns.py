import base64

from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from connection.connection import ensure_login
from generics import ApiResponse


CHECKRUNS_URI = "/sap/bc/adt/checkruns"
CHECKRUNS_REPORTER = "abapCheckRun"


class CheckMessageOutput(BaseModel):
    """One diagnostic message returned by the SAP syntax checker for one source position."""

    uri: str = Field(
        ...,
        description=(
            "ADT source URI with line and column, e.g. '.../source/main#start=9,4'. "
            "Use the line number to locate the issue in the source code."
        )
    )
    type: str = Field(
        ...,
        description="Severity: 'E' (error), 'W' (warning), 'I' (information)."
    )
    shortText: str = Field("", description="Short description of the diagnostic message.")
    msgId: str = Field("", description="SAP message class ID, e.g. 'SDDL_PARSER_MSG'.")
    msgNo: str = Field("", description="SAP message number within the message class.")


class CheckReportOutput(BaseModel):
    """Syntax check result for one ADT repository object."""

    triggeringUri: str = Field(..., description="ADT URI of the object that was checked.")
    status: str = Field(..., description="Processing status returned by SAP, typically 'processed'.")
    statusText: str = Field("", description="Human-readable status description, e.g. 'Object X has been checked'.")
    messages: list[CheckMessageOutput] = Field(
        default_factory=list,
        description=(
            "Diagnostic messages from the syntax checker in source order. "
            "Empty list means no issues were found."
        )
    )
    hasErrors: bool = Field(..., description="True when at least one message with type 'E' was returned.")
    hasWarnings: bool = Field(..., description="True when at least one message with type 'W' was returned.")


class CheckRunOutput(BaseModel):
    """Aggregated syntax check result for all objects included in the check run."""

    reports: list[CheckReportOutput] = Field(
        default_factory=list,
        description="One report per checked object."
    )
    passed: bool = Field(
        ...,
        description="True when no error messages were found across all checked objects."
    )


class CheckRunResponse(ApiResponse[CheckRunOutput]):
    """Response returned by the syntax check tool."""


def _ensure_list(val) -> list:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _build_checkrun_payload(
    objectUri: str,
    sourceUri: str,
    source: str,
    version: str,
) -> str:
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    payload = {
        "chkrun:checkObjectList": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:chkrun": "http://www.sap.com/adt/checkrun",
            "chkrun:checkObject": {
                "@adtcore:uri": objectUri,
                "@chkrun:version": version,
                "chkrun:artifacts": {
                    "chkrun:artifact": {
                        "@chkrun:contentType": "text/plain; charset=utf-8",
                        "@chkrun:uri": sourceUri,
                        "chkrun:content": encoded,
                    }
                },
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def _parse_checkrun_response(response) -> CheckRunOutput:
    parsed = xmltodict.parse(
        response.text,
        force_list=("chkrun:checkReport", "chkrun:checkMessage"),
    )
    root = parsed.get("chkrun:checkRunReports", {}) or {}

    reports: list[CheckReportOutput] = []
    for report in _ensure_list(root.get("chkrun:checkReport")):
        messages: list[CheckMessageOutput] = []
        msg_list = (report.get("chkrun:checkMessageList", {}) or {})
        for msg in _ensure_list(msg_list.get("chkrun:checkMessage")):
            t100 = (msg.get("chkrun:t100Key", {}) or {})
            messages.append(CheckMessageOutput(
                uri=msg.get("@chkrun:uri", ""),
                type=msg.get("@chkrun:type", ""),
                shortText=msg.get("@chkrun:shortText", ""),
                msgId=t100.get("@chkrun:msgid", ""),
                msgNo=t100.get("@chkrun:msgno", ""),
            ))

        reports.append(CheckReportOutput(
            triggeringUri=report.get("@chkrun:triggeringUri", ""),
            status=report.get("@chkrun:status", ""),
            statusText=report.get("@chkrun:statusText", ""),
            messages=messages,
            hasErrors=any(m.type == "E" for m in messages),
            hasWarnings=any(m.type == "W" for m in messages),
        ))

    return CheckRunOutput(
        reports=reports,
        passed=all(not r.hasErrors for r in reports),
    )


def call_checkrun(
    systemId: str,
    objectUri: str,
    sourceUri: str,
    source: str,
    version: str = "inactive",
) -> CheckRunResponse:
    """Run the SAP ABAP syntax checker for one repository object through the ADT checkruns endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return CheckRunResponse.model_validate({
                "result": False, "httpCode": 401, "httpReason": "Unauthorized",
                "message": f"Cannot run syntax check because no SAP session is available: {error_msg}",
                "data": None,
            })

        if not objectUri:
            raise ValueError("objectUri is required.")
        if not sourceUri:
            raise ValueError("sourceUri is required.")

        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.checkobjects+xml",
            "Accept": "application/vnd.sap.adt.checkmessages+xml",
        }
        payload = _build_checkrun_payload(objectUri, sourceUri, source, version)
        response = get_session(systemId).post(
            f"{system_config.server}{CHECKRUNS_URI}?reporters={CHECKRUNS_REPORTER}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return CheckRunResponse.model_validate({
                "result": False, "httpCode": response.status_code, "httpReason": response.reason,
                "message": f"ADT rejected the syntax check request: {response.text}",
                "data": None,
            })

        output = _parse_checkrun_response(response)
        error_count = sum(1 for r in output.reports for m in r.messages if m.type == "E")
        warning_count = sum(1 for r in output.reports for m in r.messages if m.type == "W")

        if output.passed:
            msg = f"Syntax check passed with {warning_count} warning(s)." if warning_count else "Syntax check passed with no issues."
        else:
            msg = f"Syntax check failed: {error_count} error(s), {warning_count} warning(s)."

        return CheckRunResponse.model_validate({
            "result": output.passed,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": msg,
            "data": output,
        })
    except ValueError as exc:
        return CheckRunResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": str(exc), "data": None,
        })
    except Exception as exc:
        return CheckRunResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Unexpected error during syntax check: {str(exc)}", "data": None,
        })
