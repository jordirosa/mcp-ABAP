"""Dashboard helper logic for local MCP client inspection, updates, and tutorials."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

HTTP_DASHBOARD_MCP_ACTION_PATH = "/mcp/abap/api/dashboard/mcp-action"
HTTP_DASHBOARD_MCP_STATUS_PATH = "/mcp/abap/api/dashboard/mcp-status"
HTTP_DASHBOARD_PORT_HELP_PATH = "/mcp/abap/dashboard/help/sap-gui-port"
HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH = "/mcp/abap/api/dashboard/saplogon/import"

_DESIRED_MCP_KEY = "mcp-ABAP"
_DEFAULT_MCP_HOST = "127.0.0.1"
_DEFAULT_MCP_PORT = 8081
_DEFAULT_MCP_PATH = "/mcp/abap"
_desired_mcp_url = f"http://{_DEFAULT_MCP_HOST}:{_DEFAULT_MCP_PORT}{_DEFAULT_MCP_PATH}/"
_TUTORIAL_ASSETS = Path(__file__).resolve().parent / "assets" / "smicm_port_help"
_SCRIPTING_ASSETS = Path(__file__).resolve().parent / "assets" / "rz11_user_scripting_help"


def configure_dashboard_mcp_target(host: str, port: int, path: str) -> None:
    """Keep dashboard MCP status/actions aligned with the running HTTP endpoint."""
    global _desired_mcp_url
    normalized_host = str(host or _DEFAULT_MCP_HOST).strip() or _DEFAULT_MCP_HOST
    normalized_path = str(path or _DEFAULT_MCP_PATH).strip() or _DEFAULT_MCP_PATH
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    _desired_mcp_url = f"http://{normalized_host}:{int(port)}{normalized_path.rstrip('/')}/"


def _read_text_tolerant(path: Path) -> str:
    """Read local text config files while tolerating BOM-prefixed encodings."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8")


def _write_text_exact(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(text)


def _client_paths() -> dict[str, Path]:
    home = Path.home()
    return {
        "copilot": home / ".copilot" / "mcp-config.json",
        "codex": home / ".codex" / "config.toml",
        "claude": _claude_desktop_config_path(),
    }


def _client_name(client_id: str) -> str:
    return {
        "copilot": "Copilot CLI",
        "codex": "OpenAI Codex",
        "claude": "Claude Desktop",
    }[client_id]


def _client_command(client_id: str) -> str:
    return {
        "copilot": "copilot",
        "codex": "codex",
        "claude": "",
    }[client_id]


def _claude_desktop_config_path() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    packages_dir = local_app_data / "Packages"
    package_dirs = sorted(packages_dir.glob("Claude_*")) if packages_dir.exists() else []

    for package_dir in package_dirs:
        config_dir = package_dir / "LocalCache" / "Roaming" / "Claude"
        if config_dir.exists():
            return config_dir / "claude_desktop_config.json"

    if package_dirs:
        return package_dirs[0] / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"

    package_family_name = _claude_desktop_package_family_name()
    if package_family_name:
        return (
            local_app_data
            / "Packages"
            / package_family_name
            / "LocalCache"
            / "Roaming"
            / "Claude"
            / "claude_desktop_config.json"
        )

    return local_app_data / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"


def _claude_desktop_package_family_name() -> str:
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-AppxPackage -Name Claude).PackageFamilyName",
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""


def _is_claude_desktop_installed() -> bool:
    path = _claude_desktop_config_path()
    if "*" not in str(path) and path.parent.exists():
        return True
    return bool(_claude_desktop_package_family_name())


def _is_abap_mcp_candidate(name: str, config: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(part)
        for part in [
            name,
            config.get("url", ""),
            config.get("command", ""),
            " ".join(str(arg) for arg in config.get("args", []) or []),
        ]
    ).lower()
    return "abap" in haystack and "mcp" in haystack


def _default_status(client_id: str) -> dict[str, Any]:
    cli_installed = _is_claude_desktop_installed() if client_id == "claude" else shutil.which(_client_command(client_id)) is not None
    return {
        "id": client_id,
        "name": _client_name(client_id),
        "path": str(_client_paths()[client_id]),
        "cliInstalled": cli_installed,
        "mcpState": "missing",
        "mcpLabel": "Sin entrada",
        "actions": ["insert"],
        "detail": "No se ha encontrado ninguna entrada ABAP MCP.",
    }


def _parse_error_status(status: dict[str, Any], error: Exception) -> dict[str, Any]:
    status.update(
        {
            "mcpState": "mismatch",
            "mcpLabel": "Config inválida",
            "actions": [],
            "detail": f"No se pudo leer el fichero de configuración: {error}",
        }
    )
    return status


def _normalize_toml_table_headers(text: str) -> str:
    """Move inline TOML table headers to their own line before parsing/writing."""
    normalized_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("[") and "]" in stripped:
            header_end = line.find("]")
            remainder = line[header_end + 1 :].strip()
            if remainder:
                normalized_lines.append(line[: header_end + 1].rstrip())
                normalized_lines.append(remainder)
                continue
        normalized_lines.append(line)
    newline = "\r\n" if "\r\n" in text else "\n"
    return newline.join(normalized_lines) + (newline if text.endswith(("\n", "\r")) else "")


def _inspect_copilot() -> dict[str, Any]:
    status = _default_status("copilot")
    status["cliDetail"] = "CLI detectado en PATH." if status["cliInstalled"] else "CLI no detectado en PATH."
    path = _client_paths()["copilot"]
    if not path.exists():
        status["detail"] = "No se ha encontrado el fichero de configuración."
        return status

    try:
        payload = json.loads(_read_text_tolerant(path))
    except json.JSONDecodeError as exc:
        return _parse_error_status(status, exc)
    servers = payload.get("mcpServers", {}) if isinstance(payload, dict) else {}
    candidates = {
        key: value
        for key, value in servers.items()
        if isinstance(value, dict) and _is_abap_mcp_candidate(key, value)
    }
    if not candidates:
        return status

    for key, value in candidates.items():
        if value.get("type") == "http" and value.get("url") == _desired_mcp_url:
            status.update(
                {
                    "mcpState": "match",
                    "mcpLabel": "Correcto",
                    "actions": ["delete"],
                    "detail": f"Entrada {key} apunta a {_desired_mcp_url}",
                }
            )
            return status

    key = next(iter(candidates))
    status.update(
        {
            "mcpState": "mismatch",
            "mcpLabel": "Ajustable",
            "actions": ["adjust", "delete"],
            "detail": f"Entrada {key} detectada con configuración distinta.",
        }
    )
    return status


def _inspect_codex() -> dict[str, Any]:
    status = _default_status("codex")
    status["cliDetail"] = "CLI detectado en PATH." if status["cliInstalled"] else "CLI no detectado en PATH."
    path = _client_paths()["codex"]
    if not path.exists():
        status["detail"] = "No se ha encontrado el fichero de configuración."
        return status

    try:
        payload = tomllib.loads(_normalize_toml_table_headers(_read_text_tolerant(path)))
    except tomllib.TOMLDecodeError as exc:
        return _parse_error_status(status, exc)
    servers = payload.get("mcp_servers", {}) if isinstance(payload, dict) else {}
    candidates = {
        key: value
        for key, value in servers.items()
        if isinstance(value, dict) and _is_abap_mcp_candidate(key, value)
    }
    if not candidates:
        return status

    for key, value in candidates.items():
        if value.get("url") == _desired_mcp_url:
            status.update(
                {
                    "mcpState": "match",
                    "mcpLabel": "Correcto",
                    "actions": ["delete"],
                    "detail": f"Entrada {key} apunta a {_desired_mcp_url}",
                }
            )
            return status

    key = next(iter(candidates))
    status.update(
        {
            "mcpState": "mismatch",
            "mcpLabel": "Ajustable",
            "actions": ["adjust", "delete"],
            "detail": f"Entrada {key} detectada con configuración distinta.",
        }
    )
    return status


def _desired_claude_mcp_config() -> dict[str, Any]:
    return {
        "command": "npx",
        "args": ["mcp-remote", _desired_mcp_url, "--allow-http"],
    }


def _is_desired_claude_mcp_config(value: dict[str, Any]) -> bool:
    desired = _desired_claude_mcp_config()
    return value.get("command") == desired["command"] and value.get("args") == desired["args"]


def _inspect_claude() -> dict[str, Any]:
    status = _default_status("claude")
    status["cliDetail"] = (
        "Claude Desktop detectado."
        if status["cliInstalled"]
        else "Claude Desktop no detectado como app instalada."
    )
    if not status["cliInstalled"]:
        status["actions"] = []
        status["detail"] = "Instala Claude Desktop para poder configurar su MCP local."
        return status

    path = _client_paths()["claude"]
    if not path.exists():
        status["detail"] = "No se ha encontrado claude_desktop_config.json."
        return status

    try:
        payload = json.loads(_read_text_tolerant(path))
    except json.JSONDecodeError as exc:
        return _parse_error_status(status, exc)
    servers = payload.get("mcpServers", {}) if isinstance(payload, dict) else {}
    candidates = {
        key: value
        for key, value in servers.items()
        if isinstance(value, dict) and _is_abap_mcp_candidate(key, value)
    }
    if not candidates:
        return status

    for key, value in candidates.items():
        if _is_desired_claude_mcp_config(value):
            status.update(
                {
                    "mcpState": "match",
                    "mcpLabel": "Correcto",
                    "actions": ["delete"],
                    "detail": f"Entrada {key} usa npx mcp-remote hacia {_desired_mcp_url}",
                }
            )
            return status

    key = next(iter(candidates))
    status.update(
        {
            "mcpState": "mismatch",
            "mcpLabel": "Ajustable",
            "actions": ["adjust", "delete"],
            "detail": f"Entrada {key} detectada con configuración distinta.",
        }
    )
    return status


def get_dashboard_mcp_status() -> dict[str, Any]:
    """Return MCP status rows for the supported local MCP clients."""
    return {"clients": [_inspect_copilot(), _inspect_codex(), _inspect_claude()]}


def _rewrite_json_mcp_servers(path: Path, action: str, desired_config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(_read_text_tolerant(path)) if path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
    servers = {
        key: value
        for key, value in servers.items()
        if not (isinstance(value, dict) and _is_abap_mcp_candidate(key, value))
    }
    if action in {"insert", "adjust"}:
        servers[_DESIRED_MCP_KEY] = desired_config
    payload["mcpServers"] = servers
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _rewrite_copilot(action: str) -> None:
    path = _client_paths()["copilot"]
    _rewrite_json_mcp_servers(path, action, {"type": "http", "url": _desired_mcp_url})


def _rewrite_codex(action: str) -> None:
    path = _client_paths()["codex"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    text = _normalize_toml_table_headers(_read_text_tolerant(path))
    newline = "\r\n" if "\r\n" in text else "\n"
    payload = tomllib.loads(text or "") if text.strip() else {}
    servers = payload.get("mcp_servers", {}) if isinstance(payload, dict) else {}
    remove_keys = [
        key for key, value in servers.items() if isinstance(value, dict) and _is_abap_mcp_candidate(key, value)
    ]

    out_lines: list[str] = []
    skip = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[mcp_servers.") and stripped.endswith("]"):
            key = stripped[len("[mcp_servers.") : -1]
            skip = key in remove_keys
            if skip:
                continue
        elif stripped.startswith("[") and stripped.endswith("]"):
            skip = False
        if not skip:
            out_lines.append(line)

    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    if action in {"insert", "adjust"}:
        block = [
            f"[mcp_servers.{_DESIRED_MCP_KEY}]",
            f'url = "{_desired_mcp_url}"',
            "tool_timeout_sec = 120",
        ]
        if out_lines:
            out_lines.extend(["", *block])
        else:
            out_lines.extend(block)

    result = newline.join(out_lines).strip()
    _write_text_exact(path, (result + newline) if result else "")


def _rewrite_claude(action: str) -> None:
    path = _client_paths()["claude"]
    if "*" in str(path):
        raise ValueError("Claude Desktop no está instalado o no se pudo resolver su carpeta de configuración.")
    _rewrite_json_mcp_servers(path, action, _desired_claude_mcp_config())


def apply_dashboard_mcp_action(client_id: str, action: str) -> dict[str, Any]:
    """Apply one dashboard MCP action to one local client config."""
    if client_id not in {"copilot", "codex", "claude"}:
        raise ValueError("Unsupported dashboard client.")
    if action not in {"insert", "adjust", "delete"}:
        raise ValueError("Unsupported dashboard action.")

    if client_id == "copilot":
        _rewrite_copilot(action)
    elif client_id == "codex":
        _rewrite_codex(action)
    else:
        _rewrite_claude(action)

    clients = get_dashboard_mcp_status()["clients"]
    updated = next(client for client in clients if client["id"] == client_id)
    return {"message": f"Acción {action} aplicada sobre {_client_name(client_id)}.", "client": updated}


def _tutorial_image_data_uri(file_name: str) -> str:
    """Return one embedded data URI for a tutorial BMP screenshot."""
    image_path = _TUTORIAL_ASSETS / file_name
    if not image_path.exists():
        return ""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/bmp;base64,{encoded}"


def _scripting_image_data_uri(file_name: str) -> str:
    """Return one embedded data URI for a user scripting tutorial BMP screenshot."""
    image_path = _SCRIPTING_ASSETS / file_name
    if not image_path.exists():
        return ""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/bmp;base64,{encoded}"


def render_dashboard_port_help_html() -> str:
    """Render the SAP GUI help for user scripting and manual HTTPS port lookup."""
    rz11_initial_image = _scripting_image_data_uri("01_rz11_initial.bmp")
    rz11_details_image = _scripting_image_data_uri("02_rz11_details.bmp")
    rz11_popup_image = _scripting_image_data_uri("03_rz11_change_popup.bmp")
    initial_image = _tutorial_image_data_uri("01_initial.bmp")
    smicm_image = _tutorial_image_data_uri("02_smicm.bmp")
    services_image = _tutorial_image_data_uri("03_services.bmp")

    def _img_block(title: str, data_uri: str, body: str) -> str:
        image_html = f'<img src="{data_uri}" alt="{title}" />' if data_uri else '<div class="missing">No se ha encontrado la captura.</div>'
        return f"""
        <section class="step">
          <div class="step-text">
            <h2>{title}</h2>
            <p>{body}</p>
          </div>
          <div class="shot">{image_html}</div>
        </section>
        """

    scripting_steps_html = "".join(
        [
            _img_block(
                "1. Abrir RZ11 y buscar el parámetro",
                rz11_initial_image,
                "Entra en <code>RZ11</code>, escribe <code>sapgui/user_scripting</code> y pulsa <strong>Display</strong>.",
            ),
            _img_block(
                "2. Revisar el valor actual",
                rz11_details_image,
                "En la pantalla de detalle revisa el parámetro. Si el valor actual ya está en <code>TRUE</code>, SAP GUI Scripting ya está activo y no hace falta cambiar nada.",
            ),
            _img_block(
                "3. Activarlo si está deshabilitado",
                rz11_popup_image,
                "Pulsa <strong>Change Value</strong>. Si tienes permisos y el parámetro lo permite, cambia el valor nuevo a <code>TRUE</code> y guarda. Si no puedes hacerlo, usa la ruta manual de <code>SMICM</code> que aparece más abajo.",
            ),
        ]
    )

    smicm_steps_html = "".join(
        [
            _img_block(
                "1. Partir de SAP Easy Access",
                initial_image,
                "Abre SAP GUI en el sistema objetivo y sitúate en la pantalla principal. Desde aquí lanzaremos la transacción técnica.",
            ),
            _img_block(
                "2. Ejecutar la transacción SMICM",
                smicm_image,
                "Escribe <code>SMICM</code> en el campo de comandos y pulsa Intro. Entrarás en el ICM Monitor del servidor de aplicación.",
            ),
            _img_block(
                "3. Ir a Goto -> Services",
                services_image,
                "En el monitor, abre el menú <code>Goto</code> y entra en <code>Services</code>. En la tabla busca la fila <code>HTTPS</code>. En A4H el puerto visible es <strong>50001</strong>.",
            ),
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tutorial SAP GUI - Encontrar puerto HTTPS</title>
  <style>
    :root {{
      --bg: #0b1016;
      --panel: #131c28;
      --panel-2: #192434;
      --ink: #eef5ff;
      --muted: #9fb0c6;
      --line: rgba(154, 178, 207, 0.16);
      --accent: #64d2ff;
      --accent-2: #2fb5e9;
      --shadow: rgba(0, 0, 0, 0.42);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(100, 210, 255, 0.14) 0, transparent 26%),
        linear-gradient(145deg, #081018 0%, #0c1117 36%, #121b27 100%);
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 34px 20px 52px; }}
    .hero {{
      background: linear-gradient(180deg, rgba(24, 34, 49, 0.96) 0%, rgba(15, 22, 32, 0.96) 100%);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 28px;
      box-shadow: 0 18px 44px var(--shadow);
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0 0 10px; font-size: 34px; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    code {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.06);
      padding: 2px 6px;
      border-radius: 8px;
      color: #d8e7ff;
    }}
    .note {{
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 14px;
      background: rgba(100, 210, 255, 0.08);
      border: 1px solid rgba(100, 210, 255, 0.16);
    }}
    .step {{
      display: grid;
      grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
      gap: 18px;
      margin-bottom: 18px;
      background: linear-gradient(180deg, rgba(24, 34, 49, 0.96) 0%, rgba(15, 22, 32, 0.96) 100%);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 22px;
      box-shadow: 0 18px 44px var(--shadow);
    }}
    .step h2 {{ margin: 0 0 10px; font-size: 24px; }}
    .shot {{
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
    }}
    .shot img {{
      display: block;
      width: 100%;
      height: auto;
      border-radius: 10px;
      box-shadow: 0 14px 30px rgba(0, 0, 0, 0.24);
      background: #fff;
    }}
    .missing {{
      color: var(--muted);
      padding: 24px;
      text-align: center;
    }}
    @media (max-width: 900px) {{
      .step {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Ayuda para importar desde SAP Logon</h1>
      <p>El botón <strong>Importar desde SAP Logon</strong> intenta abrir una sesión temporal de SAP GUI para localizar automáticamente el puerto HTTPS. Para que esa automatización funcione, <strong>SAP GUI Scripting</strong> debe estar activo.</p>
      <div class="note">
        <strong>Orden recomendada:</strong><br />
        1. Verifica o activa <code>sapgui/user_scripting</code> en <code>RZ11</code>.<br />
        2. Si no puedes activarlo, usa la búsqueda manual del puerto en <code>SMICM</code>.<br />
        3. El dato que necesitas es la fila <code>HTTPS</code> y su columna <code>Service Name/Port</code>.
      </div>
    </div>
    <div class="hero">
      <h2 style="margin:0 0 10px;">Parte 1. Activar SAP GUI Scripting en RZ11</h2>
      <p>Sin scripting activo, el dashboard no puede abrir una sesión SAP GUI temporal ni navegar solo hasta <code>SMICM</code>. Si el parámetro está a <code>TRUE</code>, el import automático ya debería poder intentarlo.</p>
    </div>
    {scripting_steps_html}
    <div class="hero">
      <h2 style="margin:0 0 10px;">Parte 2. Método manual para localizar el puerto HTTPS</h2>
      <p>Si no puedes activar scripting, sigue este flujo manual en SAP GUI y copia el puerto al campo <code>Servidor</code> del dashboard.</p>
      <div class="note">
        <strong>Ruta:</strong> <code>SMICM</code> -> <code>Goto</code> -> <code>Services</code><br />
        <strong>Qué buscar:</strong> la fila con protocolo <code>HTTPS</code> y el valor de la columna <code>Service Name/Port</code>.
      </div>
    </div>
    {smicm_steps_html}
  </div>
</body>
</html>"""
