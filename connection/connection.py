import requests
from requests.auth import HTTPBasicAuth
from pydantic import BaseModel
import urllib3

from configuration import get_session, get_system_config, set_session
import configuration
from generics import ApiResponse


if any(not config.verify_ssl for config in configuration.SYSTEM_CONFIGS.values()):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LoginResponse(ApiResponse[BaseModel]):
    """Response model for opening an authenticated SAP session."""


class LogoutResponse(ApiResponse[BaseModel]):
    """Response model for closing the current SAP session."""


def build_adt_headers(
    *,
    sessionType: str = "stateless",
    includeCsrfToken: bool = False,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build ADT request headers with an explicit SAP session type."""
    headers = {
        "X-sap-adt-sessiontype": sessionType
    }

    if includeCsrfToken:
        headers["X-CSRF-Token"] = "Fetch"

    if extra:
        headers.update(extra)

    return headers


def ensure_login(systemId: str) -> tuple[bool, str]:
    """Ensure there is an active session for one SAP system."""
    if get_session(systemId) is None:
        return False, f"Login required for system {systemId}: no active session. Call login first."

    return True, ""


def get_csrf_token(systemId: str) -> str:
    """Fetch the CSRF token for one SAP system and initialize its session if needed."""
    system_config = get_system_config(systemId)
    session = get_session(systemId)

    if session is None:
        session = requests.Session()
        session.auth = HTTPBasicAuth(system_config.user, system_config.password)
        session.verify = system_config.verify_ssl
        session.headers.pop("X-CSRF-Token", None)

    url = (
        f"{system_config.server}/sap/bc/adt/discovery"
        f"?sap-client={system_config.client}&sap-language={system_config.language}"
    )
    headers = build_adt_headers(includeCsrfToken=True)

    response = session.get(url, headers=headers)
    if response.status_code != 200:
        set_session(systemId, None)
        return ""

    set_session(systemId, session)
    session.headers.update({"X-CSRF-Token": response.headers.get("X-CSRF-Token", "")})
    return response.headers.get("X-CSRF-Token", "")


def call_login(systemId: str) -> LoginResponse:
    """Open the authenticated SAP session for one configured system."""
    try:
        system_config = get_system_config(systemId)
    except KeyError as exc:
        return LoginResponse.model_validate({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None
        })

    get_csrf_token(systemId)
    if not get_session(systemId):
        return LoginResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"SAP login failed for system {system_config.id} because the CSRF token could not be retrieved.",
            "data": None
        })

    return LoginResponse.model_validate({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": f"SAP session opened successfully for system {system_config.id}.",
        "data": None
    })


def call_logout(systemId: str) -> LogoutResponse:
    """Close the SAP session for one configured system."""
    try:
        system_config = get_system_config(systemId)
    except KeyError as exc:
        return LogoutResponse.model_validate({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None
        })

    session = get_session(systemId)
    if session:
        session.close()
        set_session(systemId, None)

    return LogoutResponse.model_validate({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": f"SAP session closed successfully for system {system_config.id}.",
        "data": None
    })
