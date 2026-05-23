from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from connection.connection import ensure_login
from generics import ApiResponse


class NavigationTargetRequest(BaseModel):
    """Source location and editor buffer used to resolve an ADT navigation target."""

    sourceUri: str = Field(
        ...,
        description="ADT source URI that contains the selected ABAP symbol, usually ending in /source/main. Do not include the #start fragment.",
    )
    source: str = Field(
        ...,
        description="Current ABAP source text from the editor buffer. ADT uses this body so navigation can work with unsaved changes.",
    )
    startLine: int = Field(..., ge=1, description="ADT 1-based line where the selected ABAP symbol starts.")
    startColumn: int = Field(..., ge=1, description="ADT 1-based column where the selected ABAP symbol starts.")
    endLine: int | None = Field(
        None,
        ge=1,
        description="ADT 1-based line where the selected ABAP symbol ends. Defaults to startLine when omitted.",
    )
    endColumn: int | None = Field(
        None,
        ge=1,
        description="ADT 1-based column where the selected ABAP symbol ends. Defaults to startColumn when omitted; pass the full token range when known.",
    )
    filter: Literal["definition"] = Field(
        "definition",
        description="ADT navigation filter to apply. Use definition to resolve where the selected symbol is declared.",
    )


class NavigationObjectReference(BaseModel):
    """ADT object reference returned as the resolved navigation target."""

    uri: str = Field(..., description="ADT URI of the navigation target, often including a #start source position fragment.")
    type: str = Field("", description="SAP object type identifier returned by ADT when available.")
    name: str = Field("", description="Technical name of the target object or symbol when available.")
    packageName: str = Field("", description="Package that contains the target object when returned by ADT.")
    description: str = Field("", description="Short description of the target object when returned by ADT.")


class NavigationTargetOutput(BaseModel):
    """Resolved ADT navigation target for one ABAP source selection."""

    requestedUri: str = Field(..., description="Full ADT source URI sent to /sap/bc/adt/navigation/target, including the #start/#end fragment.")
    filter: str = Field(..., description="Navigation filter used for the resolution.")
    target: NavigationObjectReference = Field(..., description="Object reference returned by ADT for the resolved navigation target.")


class NavigationTargetResponse(ApiResponse[NavigationTargetOutput]):
    """Response model for resolving an ADT navigation target."""


def _build_navigation_source_uri(request: NavigationTargetRequest) -> str:
    """Build the ADT source URI with a source range fragment."""
    source_uri = str(request.sourceUri or "").strip()
    if not source_uri:
        raise ValueError("sourceUri is required.")

    base_uri = source_uri.split("#", 1)[0]
    end_line = request.endLine if request.endLine is not None else request.startLine
    end_column = request.endColumn if request.endColumn is not None else request.startColumn
    return f"{base_uri}#start={request.startLine},{request.startColumn};end={end_line},{end_column}"


def parse_navigation_target_response(response, requested_uri: str, navigation_filter: str) -> NavigationTargetResponse:
    """Parse the XML response from /sap/bc/adt/navigation/target."""
    try:
        data_dict = xmltodict.parse(response.text)
        raw_reference = data_dict.get("adtcore:objectReference", {}) or {}
        target_uri = raw_reference.get("@adtcore:uri", "")
        if not target_uri:
            raise ValueError("ADT did not return a navigation target URI.")

        return NavigationTargetResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Navigation target resolved successfully.",
            "data": NavigationTargetOutput(
                requestedUri=requested_uri,
                filter=navigation_filter,
                target=NavigationObjectReference(
                    uri=target_uri,
                    type=raw_reference.get("@adtcore:type", ""),
                    name=raw_reference.get("@adtcore:name", ""),
                    packageName=raw_reference.get("@adtcore:packageName", ""),
                    description=raw_reference.get("@adtcore:description", ""),
                ),
            ),
        })
    except Exception as exc:
        return NavigationTargetResponse.model_validate({
            "result": False,
            "httpCode": response.status_code if hasattr(response, "status_code") else 500,
            "httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
            "message": f"Failed to parse the navigation target response: {str(exc)}",
            "data": None,
        })


def call_navigation_target(systemId: str, request: NavigationTargetRequest) -> NavigationTargetResponse:
    """Resolve the ADT definition target for a symbol selection in ABAP source code."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return NavigationTargetResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot resolve the navigation target because no SAP session is available: {error_msg}",
                "data": None,
            })

        requested_uri = _build_navigation_source_uri(request)
        system_config = get_system_config(systemId)
        encoded_uri = quote(requested_uri, safe="")
        encoded_filter = quote(request.filter, safe="")
        url = f"{system_config.server}/sap/bc/adt/navigation/target?uri={encoded_uri}&filter={encoded_filter}"
        headers = {
            "Accept": "application/xml",
            "Content-Type": "text/plain",
        }

        response = get_session(systemId).post(url, headers=headers, data=request.source)
        if response.status_code != 200:
            return NavigationTargetResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the navigation target request: {response.text}",
                "data": None,
            })

        return parse_navigation_target_response(response, requested_uri, request.filter)
    except ValueError as exc:
        return NavigationTargetResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return NavigationTargetResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while resolving the navigation target: {str(exc)}",
            "data": None,
        })
