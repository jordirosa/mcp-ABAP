from urllib.parse import quote

from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from generics import ApiResponse


CODE_COMPLETION_RESULTS_MIME = "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.codecompletion.Results"
ELEMENT_INFO_ACCEPT = "application/vnd.sap.adt.elementinfo+xml;q=0.9, text/plain;q=0.1"


class CodeCompletionProposalsRequest(BaseModel):
    """ABAP editor buffer and cursor position used to request ADT code completion."""

    sourceUri: str = Field(
        ...,
        description="ADT source URI containing the ABAP code, usually ending in /source/main. Existing # fragments are ignored.",
    )
    source: str = Field(
        ...,
        description="Current ABAP source text from the editor buffer. ADT uses this body so completion can work with unsaved changes.",
    )
    line: int = Field(..., ge=1, description="1-based line where completion should be calculated.")
    column: int = Field(..., ge=1, description="1-based column where completion should be calculated.")
    signalCompleteness: bool = Field(True, description="Whether ADT should signal completion-list completeness, matching Eclipse's signalCompleteness query parameter.")
    includeElementInfo: bool = Field(False, description="When true, also call ADT elementinfo for the requested element info position.")
    elementInfoLine: int | None = Field(None, ge=1, description="1-based line for the optional elementinfo request. Defaults to line when omitted.")
    elementInfoColumn: int | None = Field(None, ge=1, description="1-based column for the optional elementinfo request. Defaults to column when omitted.")


class CodeCompletionProposal(BaseModel):
    """One raw ADT code completion proposal normalized from SCC_COMPLETION."""

    identifier: str = Field("", description="Completion text proposed by ADT.")
    kind: int = Field(0, description="ADT completion kind code.")
    icon: int = Field(0, description="ADT icon code for the proposal.")
    subicon: int = Field(0, description="ADT subicon code for the proposal.")
    bold: bool = Field(False, description="Whether ADT marks this proposal as bold.")
    quickinfoEvent: bool = Field(False, description="Whether additional element information can be requested.")
    insertEvent: bool = Field(False, description="Whether ADT reports a special insert event for this proposal.")
    isMeta: bool = Field(False, description="Whether this is a metadata proposal such as @end.")
    prefixLength: int = Field(0, description="Number of already typed prefix characters ADT expects to replace.")
    role: int = Field(0, description="ADT semantic role code.")
    location: int = Field(0, description="ADT location code.")
    grade: int = Field(0, description="ADT ranking or quality grade.")
    visibility: int = Field(0, description="ADT visibility code.")
    isInherited: bool = Field(False, description="Whether ADT marks the proposal as inherited.")
    prop1: int = Field(0, description="ADT proposal property flag 1.")
    prop2: int = Field(0, description="ADT proposal property flag 2.")
    prop3: int = Field(0, description="ADT proposal property flag 3.")
    syntaxContext: int = Field(0, description="ADT syntax context code.")


class CodeCompletionElementInfo(BaseModel):
    """Additional information returned by ADT for one code completion element."""

    name: str = Field("", description="Element name returned by ADT.")
    properties: dict[str, str] = Field(default_factory=dict, description="Element properties such as abapType, visibility, paramType, optional, or byValue.")


class CodeCompletionProposalsOutput(BaseModel):
    """Code completion proposals with optional element information."""

    requestedUri: str = Field(..., description="Full ADT source URI sent to the proposal endpoint, including the #start position.")
    totalCount: int = Field(0, description="Number of completion proposals returned by ADT, including metadata proposals such as @end.")
    proposals: list[CodeCompletionProposal] = Field(default_factory=list, description="Completion proposals returned by ADT.")
    elementInfoRequestedUri: str = Field("", description="Full ADT source URI sent to elementinfo when includeElementInfo is true.")
    elementInfo: CodeCompletionElementInfo | None = Field(None, description="Optional element information returned by ADT.")


class CodeCompletionProposalsResponse(ApiResponse[CodeCompletionProposalsOutput]):
    """Response model for ABAP ADT code completion proposals."""


def _ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_bool(value) -> bool:
    return str(value or "0").upper() in {"1", "TRUE", "X"}


def _build_codecompletion_uri(sourceUri: str, line: int, column: int) -> str:
    source_uri = str(sourceUri or "").strip()
    if not source_uri:
        raise ValueError("sourceUri is required.")

    base_uri = source_uri.split("#", 1)[0]
    return f"{base_uri}#start={line},{column}"


def parse_codecompletion_proposals_response(response, requested_uri: str) -> CodeCompletionProposalsOutput:
    """Parse ABAP XML returned by /abapsource/codecompletion/proposal."""
    data_dict = xmltodict.parse(response.text)
    data_root = (((data_dict.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
    raw_completions = _ensure_list(data_root.get("SCC_COMPLETION", []))

    proposals = [
        CodeCompletionProposal(
            identifier=str(raw.get("IDENTIFIER", "") or ""),
            kind=_to_int(raw.get("KIND")),
            icon=_to_int(raw.get("ICON")),
            subicon=_to_int(raw.get("SUBICON")),
            bold=_to_bool(raw.get("BOLD")),
            quickinfoEvent=_to_bool(raw.get("QUICKINFO_EVENT")),
            insertEvent=_to_bool(raw.get("INSERT_EVENT")),
            isMeta=_to_bool(raw.get("IS_META")) or str(raw.get("IDENTIFIER", "") or "") == "@end",
            prefixLength=_to_int(raw.get("PREFIXLENGTH")),
            role=_to_int(raw.get("ROLE")),
            location=_to_int(raw.get("LOCATION")),
            grade=_to_int(raw.get("GRADE")),
            visibility=_to_int(raw.get("VISIBILITY")),
            isInherited=_to_bool(raw.get("IS_INHERITED")),
            prop1=_to_int(raw.get("PROP1")),
            prop2=_to_int(raw.get("PROP2")),
            prop3=_to_int(raw.get("PROP3")),
            syntaxContext=_to_int(raw.get("SYNTCNTXT")),
        )
        for raw in raw_completions
    ]

    return CodeCompletionProposalsOutput(
        requestedUri=requested_uri,
        totalCount=len(proposals),
        proposals=proposals,
    )


def parse_codecompletion_element_info_response(response) -> CodeCompletionElementInfo:
    """Parse XML returned by /abapsource/codecompletion/elementinfo."""
    data_dict = xmltodict.parse(response.text)
    root = data_dict.get("abapsource:elementInfo", {}) or {}
    properties_root = root.get("abapsource:properties", {}) or {}
    raw_entries = _ensure_list(properties_root.get("abapsource:entry", []))
    properties = {
        str(entry.get("@abapsource:key", "") or ""): str(entry.get("#text", "") or "")
        for entry in raw_entries
        if entry.get("@abapsource:key", "")
    }
    return CodeCompletionElementInfo(
        name=root.get("@adtcore:name", ""),
        properties=properties,
    )


def call_codecompletion_proposals(systemId: str, request: CodeCompletionProposalsRequest) -> CodeCompletionProposalsResponse:
    """Request ABAP code completion proposals and optionally element information through ADT."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return CodeCompletionProposalsResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot calculate code completion because no SAP session is available: {error_msg}",
                "data": None,
            })

        requested_uri = _build_codecompletion_uri(request.sourceUri, request.line, request.column)
        system_config = get_system_config(systemId)
        url = (
            f"{system_config.server}/sap/bc/adt/abapsource/codecompletion/proposal"
            f"?uri={quote(requested_uri, safe='')}&signalCompleteness={str(request.signalCompleteness).lower()}"
        )
        headers = build_adt_headers(
            sessionType="stateful",
            extra={
                "Accept": CODE_COMPLETION_RESULTS_MIME,
                "Content-Type": "text/plain",
                "x-sap-adt-softstate": "true",
            },
        )

        response = get_session(systemId).post(url, headers=headers, data=request.source)
        if response.status_code != 200:
            return CodeCompletionProposalsResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the code completion request: {response.text}",
                "data": None,
            })

        output = parse_codecompletion_proposals_response(response, requested_uri)
        if request.includeElementInfo:
            element_line = request.elementInfoLine if request.elementInfoLine is not None else request.line
            element_column = request.elementInfoColumn if request.elementInfoColumn is not None else request.column
            element_uri = _build_codecompletion_uri(request.sourceUri, element_line, element_column)
            element_url = (
                f"{system_config.server}/sap/bc/adt/abapsource/codecompletion/elementinfo"
                f"?uri={quote(element_uri, safe='')}"
            )
            element_headers = build_adt_headers(
                sessionType="stateful",
                extra={
                    "Accept": ELEMENT_INFO_ACCEPT,
                    "Content-Type": "text/plain",
                    "x-sap-adt-softstate": "true",
                },
            )
            element_response = get_session(systemId).post(element_url, headers=element_headers, data=request.source)
            if element_response.status_code != 200:
                return CodeCompletionProposalsResponse.model_validate({
                    "result": False,
                    "httpCode": element_response.status_code,
                    "httpReason": element_response.reason,
                    "message": f"ADT rejected the code completion element info request: {element_response.text}",
                    "data": None,
                })
            output.elementInfoRequestedUri = element_uri
            output.elementInfo = parse_codecompletion_element_info_response(element_response)

        return CodeCompletionProposalsResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Code completion proposals resolved successfully.",
            "data": output,
        })
    except ValueError as exc:
        return CodeCompletionProposalsResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return CodeCompletionProposalsResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while calculating code completion: {str(exc)}",
            "data": None,
        })
