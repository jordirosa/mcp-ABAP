from html.parser import HTMLParser
from urllib.parse import quote

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import ensure_login
from generics import ApiResponse


ABAP_DOCU_ACCEPT = "application/vnd.sap.adt.docu.v1+html, text/html"


class DocuAbapLanguageHelpRequest(BaseModel):
    """ABAP source selection used to retrieve keyword documentation from ADT."""

    sourceUri: str = Field(
        ...,
        description="ADT source URI containing the selected ABAP keyword or language construct, usually ending in /source/main. Do not include an existing #start fragment.",
    )
    source: str = Field(
        ...,
        description="Current ABAP source text from the editor buffer. ADT uses this body so documentation lookup works with unsaved changes.",
    )
    startLine: int = Field(
        ...,
        ge=1,
        description="ADT 1-based line where the selected ABAP keyword starts. Example: for LOOP at line 60, use 60.",
    )
    startColumn: int = Field(
        ...,
        ge=1,
        description="ADT 1-based column where the selected ABAP keyword starts. Example: for LOOP starting after two spaces, use 4 if ADT reports start=60,4.",
    )
    endLine: int | None = Field(
        None,
        ge=1,
        description="ADT 1-based line where the selected ABAP keyword ends. Defaults to startLine when omitted.",
    )
    endColumn: int | None = Field(
        None,
        ge=1,
        description="ADT 1-based column where the selected ABAP keyword ends. Defaults to startColumn when omitted; for best documentation results, pass the full selected token range.",
    )
    language: str = Field("EN", description="Documentation language to request from ADT, such as EN or DE.")
    format: str = Field("eclipse", description="ADT documentation format. Use eclipse to match the ABAP Development Tools help view.")


class DocuAbapLanguageHelpOutput(BaseModel):
    """ABAP keyword documentation returned by ADT."""

    requestedUri: str = Field(..., description="Full ADT source URI sent to the documentation endpoint, including the #start/#end selection fragment.")
    language: str = Field(..., description="Documentation language used in the request.")
    format: str = Field(..., description="Documentation format used in the request.")
    title: str = Field("", description="HTML title extracted from the returned documentation page when present.")
    html: str = Field(..., description="Raw HTML returned by ADT, preserving links and SAP formatting.")
    plainText: str = Field("", description="Readable text extracted from the HTML body for AI consumption.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class DocuAbapLanguageHelpResponse(ApiResponse[DocuAbapLanguageHelpOutput]):
    """Response model for ABAP language keyword documentation lookup."""


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        normalized = tag.lower()
        if normalized in {"script", "style"}:
            self._skip_depth += 1
        if normalized == "title":
            self._title_depth += 1
        if normalized in {"p", "br", "div", "h1", "h2", "h3", "h4", "li", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        normalized = tag.lower()
        if normalized in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1
        if normalized in {"p", "div", "h1", "h2", "h3", "h4", "li", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = str(data or "").strip()
        if not text:
            return
        if self._title_depth:
            self.title_parts.append(text)
        self.text_parts.append(text)


def _html_to_text(html: str) -> tuple[str, str]:
    parser = _VisibleTextParser()
    parser.feed(html or "")
    title = " ".join(parser.title_parts).strip()
    lines = []
    for line in " ".join(parser.text_parts).splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            lines.append(cleaned)
    return title, "\n".join(lines)


def _build_docu_abap_source_uri(request: DocuAbapLanguageHelpRequest) -> str:
    source_uri = str(request.sourceUri or "").strip()
    if not source_uri:
        raise ValueError("sourceUri is required.")

    base_uri = source_uri.split("#", 1)[0]
    end_line = request.endLine if request.endLine is not None else request.startLine
    end_column = request.endColumn if request.endColumn is not None else request.startColumn
    return f"{base_uri}#start={request.startLine},{request.startColumn};end={end_line},{end_column}"


def call_docu_abap_language_help(systemId: str, request: DocuAbapLanguageHelpRequest) -> DocuAbapLanguageHelpResponse:
    """Retrieve ABAP keyword documentation for a selected source range through ADT."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return DocuAbapLanguageHelpResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot retrieve ABAP documentation because no SAP session is available: {error_msg}",
                "data": None,
            })

        requested_uri = _build_docu_abap_source_uri(request)
        system_config = get_system_config(systemId)
        url = (
            f"{system_config.server}/sap/bc/adt/docu/abap/langu"
            f"?format={quote(request.format, safe='')}"
            f"&language={quote(request.language, safe='')}"
            f"&uri={quote(requested_uri, safe='')}"
        )
        headers = {
            "Accept": ABAP_DOCU_ACCEPT,
            "Content-Type": "text/plain",
        }

        response = get_session(systemId).post(url, headers=headers, data=request.source)
        if response.status_code != 200:
            return DocuAbapLanguageHelpResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the ABAP documentation request: {response.text}",
                "data": None,
            })

        title, plain_text = _html_to_text(response.text)
        return DocuAbapLanguageHelpResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "ABAP documentation retrieved successfully.",
            "data": DocuAbapLanguageHelpOutput(
                requestedUri=requested_uri,
                language=request.language,
                format=request.format,
                title=title,
                html=response.text,
                plainText=plain_text,
                contentType=response.headers.get("Content-Type", ""),
            ),
        })
    except ValueError as exc:
        return DocuAbapLanguageHelpResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DocuAbapLanguageHelpResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while retrieving ABAP documentation: {str(exc)}",
            "data": None,
        })
