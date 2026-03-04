import requests
from requests.auth import HTTPBasicAuth
from pydantic import BaseModel
import urllib3

from configuration import APP_CONFIG
import configuration
from generics import ApiResponse

# Suprimir warnings de SSL solo si verify_ssl est  deshabilitado
if not APP_CONFIG["verify_ssl"]:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LoginResponse(ApiResponse[BaseModel]):
    """Response model for connection tool."""

class LogoutResponse(ApiResponse[BaseModel]):
    """Response model for logout tool."""

def ensure_login() -> tuple[bool, str]:
    """Ensure there is an active session with token.

    Returns:
        tuple: (is_logged_in: bool, error_message: str)
    """
    if configuration.SESSION is None:
        return False, "Login required: No active session. Please call login first."

    return True, ""

def get_csrf_token() -> str:
    """Fetch CSRF token from SAP server and initialize session.

    Returns:
        CSRF token string needed for POST/PUT/DELETE operations
    """
    # Initialize session if not exists
    if configuration.SESSION is None:
        configuration.SESSION = requests.Session()
        configuration.SESSION.auth = HTTPBasicAuth(APP_CONFIG["user"], APP_CONFIG["password"])
        configuration.SESSION.verify = APP_CONFIG["verify_ssl"]
        configuration.SESSION.headers.pop("X-CSRF-Token", None)

    url = f"{APP_CONFIG['server']}/sap/bc/adt/discovery?sap-client={APP_CONFIG['client']}&sap-language={APP_CONFIG['language']}"
    headers = {
        "X-CSRF-Token": "Fetch"
    }

    # Use session to maintain cookies
    response = configuration.SESSION.get(url, headers=headers)
    configuration.SESSION.headers.update({"X-CSRF-Token": response.headers.get("X-CSRF-Token", "")})
    return response.headers.get("X-CSRF-Token", "")

def call_login() -> LoginResponse:
    get_csrf_token()
    if not configuration.SESSION:
        return LoginResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": "Login failed: CSRF token is empty.",
            "data": None
        })
    return LoginResponse.parse_obj({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": "Login successful.",
        "data": None
    })

def call_logout() -> LogoutResponse:
    # Close session if exists
    if configuration.SESSION:
        configuration.SESSION.close()
        configuration.SESSION = None

    return LogoutResponse.parse_obj({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": "Logout successful.",
        "data": None
    })
