from urllib.parse import quote

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from generics import ApiResponse


CLASSRUN_URI = "/sap/bc/adt/oo/classrun"


class ClassRunOutput(BaseModel):
    """Console output returned by running one ABAP class through ADT classrun."""

    uri: str = Field(..., description="ADT classrun URI used to execute the class.")
    className: str = Field(..., description="Technical ABAP class name that was executed.")
    output: str = Field(
        "",
        description=(
            "Plain-text console output returned by the class main/run entry point. "
            "Use this tool to execute executable ABAP classes from ADT, equivalent to "
            "Eclipse ADT Run As > ABAP Application (Console)."
        ),
    )
    contentType: str = Field("", description="HTTP content type returned by SAP, typically text/plain.")


class ClassRunResponse(ApiResponse[ClassRunOutput]):
    """Response model for running one executable ABAP class."""


def _normalize_class_name(name: str) -> str:
    """Normalize one ABAP class name for the ADT classrun endpoint."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("className is required.")
    return normalized


def _classrun_uri(className: str) -> str:
    """Return the ADT classrun URI for one executable ABAP class."""
    normalized_name = _normalize_class_name(className)
    return f"{CLASSRUN_URI}/{quote(normalized_name, safe='')}"


def _is_classrun_error_output(output: str) -> bool:
    """Return whether SAP encoded a classrun failure inside a successful HTTP response."""
    return str(output or "").lstrip().lower().startswith("error:")


def _clear_adt_context_cookie(session) -> None:
    """Start classrun outside any stale stateful ADT editing context."""
    cookie_jar = getattr(session, "cookies", None)
    if cookie_jar is None:
        return

    for cookie in list(cookie_jar):
        if cookie.name.lower() == "sap-contextid":
            cookie_jar.clear(cookie.domain, cookie.path, cookie.name)


def call_classrun_run(systemId: str, className: str) -> ClassRunResponse:
    """Execute one ABAP class through ADT classrun and return its text output."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassRunResponse.model_validate({
                "result": False, "httpCode": 401, "httpReason": "Unauthorized",
                "message": f"Cannot run ABAP class because no SAP session is available: {error_msg}",
                "data": None,
            })

        normalized_name = _normalize_class_name(className)
        uri = _classrun_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(
            sessionType="stateful",
            extra={"Accept": "text/plain"},
        )
        session = get_session(systemId)
        _clear_adt_context_cookie(session)
        response = session.post(
            f"{system_config.server}{uri}",
            headers=headers,
        )

        if response.status_code != 200:
            return ClassRunResponse.model_validate({
                "result": False, "httpCode": response.status_code, "httpReason": response.reason,
                "message": f"ADT rejected the classrun request: {response.text}",
                "data": None,
            })

        if _is_classrun_error_output(response.text):
            return ClassRunResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT classrun execution failed: {response.text.strip()}",
                "data": None,
            })

        output = ClassRunOutput(
            uri=uri,
            className=normalized_name,
            output=response.text,
            contentType=response.headers.get("Content-Type", ""),
        )
        return ClassRunResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": f"ABAP class {normalized_name} executed successfully.",
            "data": output,
        })
    except ValueError as exc:
        return ClassRunResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": str(exc), "data": None,
        })
    except Exception as exc:
        return ClassRunResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Unexpected error during classrun execution: {str(exc)}", "data": None,
        })
