"""Dashboard helper logic for local MCP client inspection, updates, and tutorials."""

from __future__ import annotations

import base64
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

HTTP_DASHBOARD_MCP_ACTION_PATH = "/mcp/abap/api/dashboard/mcp-action"
HTTP_DASHBOARD_MCP_STATUS_PATH = "/mcp/abap/api/dashboard/mcp-status"
HTTP_DASHBOARD_PORT_HELP_PATH = "/mcp/abap/dashboard/help/sap-gui-port"
HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH = "/mcp/abap/api/dashboard/saplogon/import"

_DESIRED_MCP_KEY = "mcp-ABAP"
_DESIRED_MCP_URL = "http://127.0.0.1:8000/mcp/abap/"
_TUTORIAL_ASSETS = Path(__file__).resolve().parent / "assets" / "smicm_port_help"
_SCRIPTING_ASSETS = Path(__file__).resolve().parent / "assets" / "rz11_user_scripting_help"


def _client_paths() -> dict[str, Path]:
    home = Path.home()
    return {
        "copilot": home / ".copilot" / "mcp-config.json",
        "codex": home / ".codex" / "config.toml",
    }


def _client_name(client_id: str) -> str:
    return {
        "copilot": "Copilot CLI",
        "codex": "OpenAI Codex",
    }[client_id]


def _client_command(client_id: str) -> str:
    return {
        "copilot": "copilot",
        "codex": "codex",
    }[client_id]


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
    return {
        "id": client_id,
        "name": _client_name(client_id),
        "path": str(_client_paths()[client_id]),
        "cliInstalled": shutil.which(_client_command(client_id)) is not None,
        "mcpState": "missing",
        "mcpLabel": "Sin entrada",
        "actions": ["insert"],
        "detail": "No se ha encontrado ninguna entrada ABAP MCP.",
    }


def _inspect_copilot() -> dict[str, Any]:
    status = _default_status("copilot")
    status["cliDetail"] = "CLI detectado en PATH." if status["cliInstalled"] else "CLI no detectado en PATH."
    path = _client_paths()["copilot"]
    if not path.exists():
        status["detail"] = "No se ha encontrado el fichero de configuración."
        return status

    payload = json.loads(path.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers", {}) if isinstance(payload, dict) else {}
    candidates = {
        key: value
        for key, value in servers.items()
        if isinstance(value, dict) and _is_abap_mcp_candidate(key, value)
    }
    if not candidates:
        return status

    for key, value in candidates.items():
        if value.get("type") == "http" and value.get("url") == _DESIRED_MCP_URL:
            status.update(
                {
                    "mcpState": "match",
                    "mcpLabel": "Correcto",
                    "actions": ["delete"],
                    "detail": f"Entrada {key} apunta a {_DESIRED_MCP_URL}",
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

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = payload.get("mcp_servers", {}) if isinstance(payload, dict) else {}
    candidates = {
        key: value
        for key, value in servers.items()
        if isinstance(value, dict) and _is_abap_mcp_candidate(key, value)
    }
    if not candidates:
        return status

    for key, value in candidates.items():
        if value.get("url") == _DESIRED_MCP_URL:
            status.update(
                {
                    "mcpState": "match",
                    "mcpLabel": "Correcto",
                    "actions": ["delete"],
                    "detail": f"Entrada {key} apunta a {_DESIRED_MCP_URL}",
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
    """Return MCP status rows for Copilot CLI and OpenAI Codex."""
    return {"clients": [_inspect_copilot(), _inspect_codex()]}


def _rewrite_copilot(action: str) -> None:
    path = _client_paths()["copilot"]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
    servers = {
        key: value
        for key, value in servers.items()
        if not (isinstance(value, dict) and _is_abap_mcp_candidate(key, value))
    }
    if action in {"insert", "adjust"}:
        servers[_DESIRED_MCP_KEY] = {"type": "http", "url": _DESIRED_MCP_URL}
    payload["mcpServers"] = servers
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _rewrite_codex(action: str) -> None:
    path = _client_paths()["codex"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
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
            f'url = "{_DESIRED_MCP_URL}"',
            "tool_timeout_sec = 120",
        ]
        if out_lines:
            out_lines.extend(["", *block])
        else:
            out_lines.extend(block)

    result = newline.join(out_lines).strip()
    path.write_text((result + newline) if result else "", encoding="utf-8")


def apply_dashboard_mcp_action(client_id: str, action: str) -> dict[str, Any]:
    """Apply one dashboard MCP action to one local client config."""
    if client_id not in {"copilot", "codex"}:
        raise ValueError("Unsupported dashboard client.")
    if action not in {"insert", "adjust", "delete"}:
        raise ValueError("Unsupported dashboard action.")

    if client_id == "copilot":
        _rewrite_copilot(action)
    else:
        _rewrite_codex(action)

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
