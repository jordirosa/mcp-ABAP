import json
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field
import requests

from generics import ApiResponse


# Cargar variables de entorno desde archivo .env
load_dotenv()


class SapSystemConfig(BaseModel):
    """Internal configuration for one SAP system target."""

    id: str = Field(..., description="Short identifier used to address the SAP system.")
    name: str = Field(..., description="Human-readable system name.")
    type: str = Field(..., description="Environment type such as Desarrollo, Calidad, Integracion or similar.")
    server: str = Field(..., description="Base URL of the SAP system.")
    user: str = Field(..., description="SAP user used for authentication.")
    password: str = Field(..., description="SAP password used for authentication.")
    client: str = Field(..., description="SAP client.")
    language: str = Field("EN", description="Default SAP logon language.")
    verify_ssl: bool = Field(False, description="Whether SSL certificates must be verified.")
    sap_gui_connection_name: str | None = Field(None, description="Optional SAP Logon entry name used to open SAP GUI sessions.")


class SapSystemInfo(BaseModel):
    """Public metadata for one configured SAP system."""

    id: str = Field(..., description="Short identifier used by MCP tools to select the SAP system.")
    name: str = Field(..., description="Human-readable SAP system name.")
    type: str = Field(..., description="Environment type label defined in the configuration.")
    server: str = Field(..., description="Base URL of the SAP system.")
    client: str = Field(..., description="Default SAP client.")
    language: str = Field(..., description="Default SAP logon language.")
    verifySsl: bool = Field(..., description="Whether SSL certificates are verified for this SAP system.")


class SapSystemListOutput(BaseModel):
    """List of SAP systems configured for this MCP server."""

    systems: list[SapSystemInfo] = Field(default_factory=list, description="Configured SAP systems available to MCP tools.")
    totalCount: int = Field(..., description="Number of configured SAP systems.")


class SapSystemListResponse(ApiResponse[SapSystemListOutput]):
    """Response model for listing configured SAP systems."""


def _parse_verify_ssl(value) -> bool:
    """Normalize SSL verification flags from environment values."""
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _load_legacy_single_system() -> list[dict]:
    """Build a single-system configuration from the legacy environment variables."""
    server = os.getenv("SAP_SERVER")
    user = os.getenv("SAP_USER")
    password = os.getenv("SAP_PASSWORD")
    client = os.getenv("SAP_CLIENT")

    if not all([server, user, password, client]):
        return []

    return [{
        "id": os.getenv("SAP_SYSTEM_ID", "DEF"),
        "name": os.getenv("SAP_SYSTEM_NAME", "Default SAP System"),
        "type": os.getenv("SAP_SYSTEM_TYPE", "Default"),
        "server": server,
        "user": user,
        "password": password,
        "client": client,
        "language": os.getenv("SAP_LANGUAGE", "EN"),
        "verify_ssl": _parse_verify_ssl(os.getenv("SAP_VERIFY_SSL", "false")),
        "sap_gui_connection_name": os.getenv("SAP_GUI_CONNECTION_NAME")
    }]


def _load_system_configs() -> dict[str, SapSystemConfig]:
    """Load SAP system configurations from SAP_SYSTEMS_JSON or the legacy single-system variables."""
    raw_json = os.getenv("SAP_SYSTEMS_JSON", "").strip()

    if raw_json:
        try:
            raw_systems = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "La variable SAP_SYSTEMS_JSON no contiene un JSON valido. "
                f"Error: {str(exc)}"
            ) from exc
    else:
        raw_systems = _load_legacy_single_system()

    if not raw_systems:
        raise ValueError(
            "No hay sistemas SAP configurados. Define SAP_SYSTEMS_JSON en el archivo .env "
            "o usa las variables legacy SAP_SERVER, SAP_USER, SAP_PASSWORD y SAP_CLIENT."
        )

    configs: dict[str, SapSystemConfig] = {}
    required_keys = ["id", "name", "type", "server", "user", "password", "client"]

    for raw_system in raw_systems:
        missing_keys = [key for key in required_keys if not raw_system.get(key)]
        if missing_keys:
            system_id = raw_system.get("id", "<sin id>")
            raise ValueError(
                f"Faltan campos obligatorios en la configuracion del sistema SAP {system_id}: "
                f"{', '.join(missing_keys)}."
            )

        normalized_id = str(raw_system["id"]).upper()
        if normalized_id in configs:
            raise ValueError(f"El identificador de sistema SAP '{normalized_id}' esta duplicado.")

        configs[normalized_id] = SapSystemConfig(
            id=normalized_id,
            name=str(raw_system["name"]),
            type=str(raw_system["type"]),
            server=str(raw_system["server"]),
            user=str(raw_system["user"]),
            password=str(raw_system["password"]),
            client=str(raw_system["client"]),
            language=str(raw_system.get("language", "EN")),
            verify_ssl=_parse_verify_ssl(raw_system.get("verify_ssl", False)),
            sap_gui_connection_name=(
                str(raw_system["sap_gui_connection_name"])
                if raw_system.get("sap_gui_connection_name")
                else None
            )
        )

    return configs


SYSTEM_CONFIGS = _load_system_configs()
SESSIONS: dict[str, requests.Session] = {}


def get_system_config(systemId: str) -> SapSystemConfig:
    """Return the configuration for one SAP system identifier."""
    normalized_id = systemId.upper()
    if normalized_id not in SYSTEM_CONFIGS:
        available_ids = ", ".join(sorted(SYSTEM_CONFIGS.keys()))
        raise KeyError(
            f"El sistema SAP '{systemId}' no existe. Sistemas disponibles: {available_ids}."
        )
    return SYSTEM_CONFIGS[normalized_id]


def get_session(systemId: str) -> requests.Session | None:
    """Return the active requests session for one SAP system identifier."""
    return SESSIONS.get(systemId.upper())


def set_session(systemId: str, session: requests.Session | None) -> None:
    """Store or clear the active requests session for one SAP system identifier."""
    normalized_id = systemId.upper()
    if session is None:
        SESSIONS.pop(normalized_id, None)
    else:
        SESSIONS[normalized_id] = session


def list_systems() -> list[SapSystemInfo]:
    """Return the configured SAP systems as MCP-friendly metadata."""
    systems: list[SapSystemInfo] = []
    for config in SYSTEM_CONFIGS.values():
        systems.append(SapSystemInfo(
            id=config.id,
            name=config.name,
            type=config.type,
            server=config.server,
            client=config.client,
            language=config.language,
            verifySsl=config.verify_ssl
        ))
    return systems


def call_sap_systems_list() -> SapSystemListResponse:
    """Return the SAP systems configured for this MCP server."""
    systems = list_systems()
    output = SapSystemListOutput(
        systems=systems,
        totalCount=len(systems)
    )

    return SapSystemListResponse.parse_obj({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": "Configured SAP systems listed successfully.",
        "data": output
    })
