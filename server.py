import argparse
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, unquote

from dashboard.dashboard import (
    HTTP_DASHBOARD_PORT_HELP_PATH,
    HTTP_DASHBOARD_MCP_ACTION_PATH,
    HTTP_DASHBOARD_MCP_STATUS_PATH,
    HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH,
    apply_dashboard_mcp_action as dashboard_apply_mcp_action,
    configure_dashboard_mcp_target,
    get_dashboard_mcp_status as dashboard_get_mcp_status_data,
    render_dashboard_port_help_html,
)
from fastmcp import FastMCP
from pydantic import Field
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from activation.activation import *
from configuration import *
from connection.connection import *
from cts.cts import *
from deletion.deletion import *
from ddic.db.settings import *
from ddic.dataelements.dataelements import *
from ddic.ddl.ddl import *
from ddic.domains.domains import *
from ddic.tables.tables import *
from generics import FileTransferOutput, FileTransferResponse
from gui.gui import *
from info_repository.info_repository import *
from knowledge.knowledge import *
from packages.packages import *
from source.functions.includes import *
from source.functions.fmodule import *
from source.functions.groups import *
from source.interfaces.interfaces import *
from source.programs.includes import *
from source.symbols import *
from utils import *
from source.classes.classes import *
from source.classes.testclasses import *
from source.programs.programs import *

LOGGER = logging.getLogger("abap_mcp")
HTTP_DASHBOARD_CONFIG_PATH = "/mcp/abap/api/dashboard/config"
HTTP_DASHBOARD_SAPLOGON_PATH = "/mcp/abap/api/dashboard/saplogon"
HTTP_DASHBOARD_MCP_STATUS_PATH = "/mcp/abap/api/dashboard/mcp-status"
HTTP_DASHBOARD_MEMORY_TREE_PATH = "/mcp/abap/api/dashboard/memory/tree"
HTTP_DASHBOARD_MEMORY_DOCUMENT_PATH = "/mcp/abap/api/dashboard/memory/document"
HTTP_DASHBOARD_PATH = "/mcp/abap/dashboard"
RUN_TRANSPORT = "stdio"
RUN_HOST = "127.0.0.1"
RUN_PORT = 8081
RUN_PATH = "/mcp/abap"


def _memory_documents_root() -> Path:
    """Return the local documents root used by the memory tab."""
    root = Path(__file__).resolve().parent / "db" / "documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_memory_relative_path(relative_path: str) -> tuple[str, Path]:
    """Validate and resolve one relative document path inside the local memory root."""
    cleaned = str(relative_path or "").strip().replace("\\", "/")
    if not cleaned:
        raise ValueError("relativePath is required.")
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        raise ValueError("relativePath must stay inside db/documents.")

    target_path = (_memory_documents_root() / cleaned).resolve()
    root = _memory_documents_root().resolve()
    if root not in [target_path, *target_path.parents]:
        raise ValueError("relativePath must stay inside db/documents.")
    return cleaned, target_path


def _build_memory_tree_node(directory: Path, root: Path) -> list[dict]:
    """Return a nested tree with folders plus md/pdf files only."""
    nodes: list[dict] = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.endswith(".meta.json"):
            continue
        if child.is_dir():
            children = _build_memory_tree_node(child, root)
            if not children:
                continue
            nodes.append({
                "type": "folder",
                "name": child.name,
                "relativePath": child.relative_to(root).as_posix(),
                "children": children,
            })
            continue

        suffix = child.suffix.lower()
        if suffix not in {".md", ".pdf"}:
            continue
        nodes.append({
            "type": "file",
            "name": child.name,
            "relativePath": child.relative_to(root).as_posix(),
            "extension": suffix[1:],
        })
    return nodes


def _memory_tree_payload() -> dict:
    """Return the local memory tree payload for the dashboard."""
    root = _memory_documents_root()
    return {
        "rootPath": str(root),
        "nodes": _build_memory_tree_node(root, root),
    }


def _load_memory_markdown(relative_path: str) -> dict:
    """Load one markdown document from memory for read-only display."""
    normalized_relative_path, target_path = _resolve_memory_relative_path(relative_path)
    if target_path.suffix.lower() != ".md":
        raise ValueError("Only markdown documents can be loaded through the markdown endpoint.")
    if not target_path.exists():
        raise FileNotFoundError(f"The memory document '{normalized_relative_path}' does not exist.")

    return {
        "relativePath": normalized_relative_path,
        "name": target_path.name,
        "extension": "md",
        "content": target_path.read_text(encoding="utf-8"),
    }


def _configure_startup_logging() -> None:
    """Configure console logging once for HTTP startup visibility."""
    if LOGGER.handlers:
        return

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


@asynccontextmanager
async def abap_lifespan(_server: FastMCP):
    """Warm heavy runtime pieces only when running the MCP over HTTP."""
    if RUN_TRANSPORT == "stdio":
        yield
        return

    _configure_startup_logging()
    startup_started = time.perf_counter()
    LOGGER.info("Arrancando servidor ABAP MCP...")
    knowledge_started = time.perf_counter()
    try:
        knowledge_info = warm_knowledge_runtime()
        LOGGER.info(
            "Knowledge runtime listo. collection=%s chroma=%s documents=%s model=%s (%.2fs)",
            knowledge_info.collectionName,
            knowledge_info.chromaPath,
            knowledge_info.documentsPath,
            knowledge_info.embeddingModel,
            time.perf_counter() - knowledge_started,
        )
    except Exception as exc:
        LOGGER.warning(
            "Knowledge runtime no se pudo precalentar y se inicializará bajo demanda: %s (%.2fs)",
            str(exc),
            time.perf_counter() - knowledge_started,
        )
    LOGGER.info("Servidor listo en http://%s:%s%s (%.2fs)", RUN_HOST, RUN_PORT, RUN_PATH, time.perf_counter() - startup_started)
    yield
    LOGGER.info("Apagando servidor ABAP MCP...")


def _dashboard_html() -> str:
    """Render the lightweight dashboard UI used to manage SAP systems in .env."""
    config_url = HTTP_DASHBOARD_CONFIG_PATH
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ABAP MCP Dashboard</title>
  <style>
    :root {{
      --bg: #0c1117;
      --bg-elevated: #111923;
      --panel: rgba(20, 30, 42, 0.9);
      --panel-strong: #182231;
      --ink: #edf3fb;
      --muted: #93a4ba;
      --line: rgba(149, 169, 195, 0.18);
      --line-strong: rgba(149, 169, 195, 0.34);
      --accent: #64d2ff;
      --accent-strong: #2fb5e9;
      --accent-soft: rgba(100, 210, 255, 0.12);
      --danger: #ff6b7a;
      --warning: #f5c76a;
      --success: #65d6a6;
      --shadow: rgba(3, 8, 15, 0.42);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(100, 210, 255, 0.14) 0, transparent 28%),
        radial-gradient(circle at top right, rgba(77, 163, 255, 0.14) 0, transparent 24%),
        linear-gradient(145deg, #081018 0%, #0c1117 36%, #121b27 100%);
      min-height: 100vh;
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 34px; }}
    p {{ color: var(--muted); margin: 0 0 24px; }}
    .panel {{
      background: linear-gradient(180deg, rgba(25, 37, 52, 0.94) 0%, rgba(17, 25, 35, 0.94) 100%);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 18px 44px var(--shadow);
      backdrop-filter: blur(12px);
      margin-bottom: 18px;
    }}
    .toolbar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }}
    .tabbar {{
      display: inline-flex;
      gap: 8px;
      padding: 6px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(9, 15, 23, 0.72);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }}
    .tab-button {{
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      border-radius: 999px;
      padding: 10px 18px;
      cursor: pointer;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .tab-button.active {{
      background: linear-gradient(180deg, rgba(100, 210, 255, 0.18) 0%, rgba(47, 181, 233, 0.16) 100%);
      color: var(--ink);
      border-color: rgba(100, 210, 255, 0.22);
      box-shadow: 0 10px 24px rgba(47, 181, 233, 0.12);
    }}
    .tab-panel[hidden] {{ display: none; }}
    .memory-layout {{
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 18px;
      min-height: 560px;
    }}
    .memory-pane {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(10, 16, 24, 0.42);
      padding: 14px;
    }}
    .memory-filter {{
      margin-bottom: 12px;
    }}
    .tree-scroll, .viewer-scroll {{
      max-height: 680px;
      overflow: auto;
    }}
    .memory-tree details {{
      margin: 4px 0;
    }}
    .memory-tree summary {{
      cursor: pointer;
      color: var(--ink);
      font-weight: 600;
      padding: 4px 6px;
      border-radius: 8px;
      list-style: none;
    }}
    .memory-tree summary:hover {{
      background: rgba(255, 255, 255, 0.04);
    }}
    .memory-tree .children {{
      margin-left: 16px;
      border-left: 1px dashed rgba(149, 169, 195, 0.18);
      padding-left: 10px;
    }}
    .memory-tree .file-row {{
      width: 100%;
      text-align: left;
      border: none;
      background: transparent;
      color: var(--ink);
      padding: 6px 8px;
      border-radius: 8px;
      cursor: pointer;
      font: inherit;
    }}
    .memory-tree .file-row:hover,
    .memory-tree .file-row.active {{
      background: rgba(100, 210, 255, 0.12);
    }}
    .memory-tree .file-meta {{
      color: var(--muted);
      font-size: 12px;
      margin-left: 6px;
    }}
    .viewer-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .viewer-frame {{
      width: 100%;
      min-height: 620px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #ffffff;
    }}
    .markdown-view {{
      padding: 16px 18px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(8, 14, 22, 0.78);
      color: var(--ink);
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: Consolas, "Courier New", monospace;
      min-height: 620px;
    }}
    .viewer-placeholder {{
      color: var(--muted);
      padding: 20px;
      border: 1px dashed var(--line-strong);
      border-radius: 12px;
      min-height: 620px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
    }}
    .button {{
      border: 1px solid transparent;
      background: linear-gradient(180deg, var(--accent) 0%, var(--accent-strong) 100%);
      color: #03131b;
      border-radius: 999px;
      padding: 10px 16px;
      cursor: pointer;
      font-weight: 600;
      box-shadow: 0 10px 24px rgba(47, 181, 233, 0.22);
    }}
    .button.secondary {{
      background: rgba(255, 255, 255, 0.02);
      color: var(--ink);
      border-color: var(--line-strong);
      box-shadow: none;
    }}
    .button.danger {{
      background: linear-gradient(180deg, #ff8794 0%, var(--danger) 100%);
      border-color: transparent;
      color: #23070b;
      box-shadow: 0 10px 24px rgba(255, 107, 122, 0.24);
    }}
    .button.warning {{
      background: linear-gradient(180deg, #ffe39a 0%, var(--warning) 100%);
      border-color: transparent;
      color: #241705;
      box-shadow: 0 10px 24px rgba(245, 199, 106, 0.22);
    }}
    .button:hover {{ filter: brightness(1.04); }}
    label {{
      display: block;
      font-weight: 700;
      margin-bottom: 8px;
      color: var(--ink);
    }}
    input[type="text"], input[type="password"], select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 11px 12px;
      background: rgba(8, 14, 22, 0.78);
      color: var(--ink);
      font: inherit;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }}
    input[type="text"]::placeholder, input[type="password"]::placeholder, textarea::placeholder {{
      color: #71829a;
    }}
    input[type="checkbox"] {{
      accent-color: var(--accent-strong);
    }}
    .field {{ margin-bottom: 14px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 12px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ font-size: 13px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }}
    .inline-actions {{ display: flex; gap: 8px; }}
    .signal {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-weight: 600;
    }}
    .signal-dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: #566476;
      box-shadow: 0 0 0 4px rgba(86, 100, 118, 0.12);
      flex: 0 0 auto;
    }}
    .signal-dot.ok {{
      background: var(--success);
      box-shadow: 0 0 0 4px rgba(101, 214, 166, 0.14);
    }}
    .signal-dot.warn {{
      background: var(--warning);
      box-shadow: 0 0 0 4px rgba(245, 199, 106, 0.14);
    }}
    .signal-dot.off {{
      background: var(--danger);
      box-shadow: 0 0 0 4px rgba(255, 107, 122, 0.14);
    }}
    .subtle {{
      color: var(--muted);
      font-size: 13px;
    }}
    .info-tip {{
      display: inline-flex;
      width: 24px;
      height: 24px;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      border: 1px solid var(--line-strong);
      background: rgba(255, 255, 255, 0.03);
      color: var(--ink);
      font-weight: 700;
      cursor: help;
    }}
    .status {{
      min-height: 24px;
      font-weight: 600;
      color: var(--accent);
    }}
    code {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.06);
      padding: 2px 6px;
      border-radius: 8px;
      color: #d8e7ff;
    }}
    dialog {{
      width: min(760px, calc(100vw - 24px));
      border: none;
      border-radius: 22px;
      padding: 0;
      box-shadow: 0 36px 72px rgba(0, 0, 0, 0.48);
      background: transparent;
    }}
    dialog::backdrop {{ background: rgba(2, 6, 12, 0.72); }}
    .modal {{
      padding: 22px;
      background: linear-gradient(180deg, rgba(24, 34, 49, 0.98) 0%, rgba(15, 22, 32, 0.98) 100%);
    }}
    .modal,
    .modal p,
    .modal table,
    .modal td {{
      color: #e8f0fb;
    }}
    .modal strong {{
      color: var(--ink);
    }}
    .modal label {{
      color: #dbe8f8;
    }}
    .modal th {{
      color: #aebed4;
    }}
    .modal .button.secondary {{
      color: #eef5ff;
    }}
    .modal .table-wrap {{
      border-radius: 14px;
      background: rgba(8, 14, 22, 0.18);
    }}
    .modal .checkbox-row label {{
      color: #dbe8f8;
      font-weight: 600;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .grid .full {{ grid-column: 1 / -1; }}
    .checkbox-row {{
      display: flex;
      gap: 8px;
      align-items: center;
      padding-top: 12px;
    }}
    @media (max-width: 760px) {{
      .grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 28px; }}
      .memory-layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <div class="toolbar" style="margin-bottom:14px;">
        <div>
          <h1>ABAP MCP Dashboard</h1>
          <p style="margin:8px 0 0;">Gestiona las conexiones SAP configuradas en el archivo <code>.env</code> sin editarlo a mano.</p>
        </div>
        <button class="button" id="saveButton" type="button">Guardar cambios</button>
      </div>
    </div>

    <div class="panel" style="padding:14px 18px;">
      <div class="tabbar" role="tablist" aria-label="Secciones del dashboard">
        <button class="tab-button active" id="tabButtonMcp" data-tab="mcp" type="button" role="tab" aria-selected="true">MCP</button>
        <button class="tab-button" id="tabButtonEnv" data-tab="env" type="button" role="tab" aria-selected="false">.env</button>
        <button class="tab-button" id="tabButtonMemory" data-tab="memory" type="button" role="tab" aria-selected="false">Memory</button>
      </div>
    </div>

    <section id="tabPanelMcp" class="tab-panel">
      <div class="panel">
        <div class="toolbar">
          <div>
            <strong>Clientes MCP</strong>
            <p style="margin:8px 0 0;">Comprueba si el servidor ABAP MCP está registrado en cada cliente local.</p>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>CLI</th>
                <th>Cliente</th>
                <th>Fichero</th>
                <th>MCP</th>
                <th>Acciones</th>
                <th>Info</th>
              </tr>
            </thead>
            <tbody id="mcpClientsTableBody"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section id="tabPanelEnv" class="tab-panel" hidden>
      <div class="panel">
        <div class="field">
          <label for="sapGuiExecutablePath">Ruta de <code>saplogon.exe</code></label>
          <input id="sapGuiExecutablePath" type="text" placeholder="Opcional. Si está vacío, el servidor intentará encontrar SAP GUI por PATH o rutas habituales." />
        </div>
        <div class="toolbar">
          <div class="status" id="status"></div>
        </div>
      </div>

      <div class="panel">
        <div class="toolbar">
          <strong>Conexiones SAP</strong>
          <button class="button secondary" id="addSystemButton" type="button">Añadir conexión</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Nombre</th>
                <th>Tipo</th>
                <th>Servidor</th>
                <th>Cliente</th>
                <th>Idioma</th>
                <th>SSL</th>
                <th>Entrada SAP GUI</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody id="systemsTableBody"></tbody>
          </table>
        </div>
      </div>
    </section>

    <section id="tabPanelMemory" class="tab-panel" hidden>
      <div class="panel">
        <div class="toolbar">
          <div>
            <strong>Memory</strong>
            <p style="margin:8px 0 0;">Explora los documentos locales de conocimiento almacenados en <code>db/documents</code>.</p>
          </div>
        </div>
        <div class="memory-layout">
          <div class="memory-pane">
            <div class="memory-filter">
              <input id="memoryFilter" type="text" placeholder="Filtrar documentos y carpetas..." />
            </div>
            <div class="tree-scroll memory-tree" id="memoryTree"></div>
          </div>
          <div class="memory-pane">
            <div class="viewer-toolbar">
              <strong id="memoryViewerTitle">Documento</strong>
              <span class="subtle" id="memoryViewerMeta">Selecciona un fichero .md o .pdf</span>
            </div>
            <div class="viewer-scroll" id="memoryViewer"></div>
          </div>
        </div>
      </div>
    </section>
  </div>

  <dialog id="editorDialog">
    <form method="dialog" class="modal" id="systemForm">
      <div class="toolbar">
        <strong id="dialogTitle">Conexión SAP</strong>
        <button class="button secondary" type="button" id="closeDialogButton">Cerrar</button>
      </div>
      <div class="grid">
        <div class="field">
          <label for="systemId">ID</label>
          <input id="systemId" type="text" maxlength="30" required />
        </div>
        <div class="field">
          <label for="systemName">Nombre</label>
          <input id="systemName" type="text" required />
        </div>
        <div class="field">
          <label for="systemType">Tipo</label>
          <input id="systemType" type="text" required />
        </div>
        <div class="field">
          <label for="systemServer">Servidor</label>
          <input id="systemServer" type="text" required />
        </div>
        <div class="field">
          <label for="systemUser">Usuario</label>
          <input id="systemUser" type="text" required />
        </div>
        <div class="field">
          <label for="systemPassword">Password</label>
          <input id="systemPassword" type="password" required />
        </div>
        <div class="field">
          <label for="systemClient">Cliente</label>
          <input id="systemClient" type="text" required />
        </div>
        <div class="field">
          <label for="systemLanguage">Idioma</label>
          <input id="systemLanguage" type="text" value="EN" />
        </div>
        <div class="field full">
          <label for="sapGuiConnectionName">Entrada de SAP GUI</label>
          <input id="sapGuiConnectionName" type="text" placeholder="Nombre exacto en SAP Logon" />
        </div>
        <div class="field full">
          <div class="inline-actions">
            <button class="button secondary" type="button" id="importSapLogonButton">Importar desde SAP Logon</button>
            <button class="button secondary" type="button" id="openPortHelpButton" title="Abrir ayuda para localizar el puerto HTTPS en SAP GUI">?</button>
          </div>
        </div>
        <div class="field full checkbox-row">
          <input id="verifySsl" type="checkbox" />
          <label for="verifySsl" style="margin:0;">Verificar certificados SSL</label>
        </div>
      </div>
      <div class="toolbar" style="margin-top:18px;">
        <div></div>
        <button class="button" type="submit">Guardar conexión</button>
      </div>
    </form>
  </dialog>

  <dialog id="sapLogonDialog">
    <div class="modal">
      <div class="toolbar">
        <strong>Entradas de SAP Logon</strong>
        <button class="button secondary" type="button" id="closeSapLogonDialogButton">Cerrar</button>
      </div>
      <p style="margin:0 0 14px; color: var(--muted);">Selecciona una entrada. El dashboard rellenará el nombre de conexión y además intentará abrir SAP GUI para localizar automáticamente el puerto HTTPS en <code>SMICM</code>.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Nombre</th>
              <th>ID sistema</th>
              <th>Host</th>
              <th>Puerto</th>
              <th>Acción</th>
            </tr>
          </thead>
          <tbody id="sapLogonTableBody"></tbody>
        </table>
      </div>
    </div>
  </dialog>

  <script>
    const configUrl = {json.dumps(config_url)};
    const sapLogonUrl = {json.dumps(HTTP_DASHBOARD_SAPLOGON_PATH)};
    const sapLogonImportUrl = {json.dumps(HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH)};
    const mcpStatusUrl = {json.dumps(HTTP_DASHBOARD_MCP_STATUS_PATH)};
    const mcpActionUrl = {json.dumps(HTTP_DASHBOARD_MCP_ACTION_PATH)};
    const portHelpUrl = {json.dumps(HTTP_DASHBOARD_PORT_HELP_PATH)};
    const memoryTreeUrl = {json.dumps(HTTP_DASHBOARD_MEMORY_TREE_PATH)};
    const memoryDocumentUrl = {json.dumps(HTTP_DASHBOARD_MEMORY_DOCUMENT_PATH)};
    const systems = [];
    const mcpClients = [];
    let sapLogonEntries = [];
    let memoryNodes = [];
    let selectedMemoryPath = "";
    let sapLogonImportMode = "auto";
    let editingIndex = null;
    let activeTab = "mcp";

    const statusEl = document.getElementById("status");
    const tableBody = document.getElementById("systemsTableBody");
    const mcpClientsTableBody = document.getElementById("mcpClientsTableBody");
    const sapGuiExecutablePathInput = document.getElementById("sapGuiExecutablePath");
    const editorDialog = document.getElementById("editorDialog");
    const sapLogonDialog = document.getElementById("sapLogonDialog");
    const sapLogonTableBody = document.getElementById("sapLogonTableBody");
    const systemForm = document.getElementById("systemForm");
    const dialogTitle = document.getElementById("dialogTitle");
    const memoryTreeEl = document.getElementById("memoryTree");
    const memoryFilterInput = document.getElementById("memoryFilter");
    const memoryViewerEl = document.getElementById("memoryViewer");
    const memoryViewerTitleEl = document.getElementById("memoryViewerTitle");
    const memoryViewerMetaEl = document.getElementById("memoryViewerMeta");
    const tabButtons = Array.from(document.querySelectorAll(".tab-button"));
    const tabPanels = {{
      mcp: document.getElementById("tabPanelMcp"),
      env: document.getElementById("tabPanelEnv"),
      memory: document.getElementById("tabPanelMemory"),
    }};

    function setActiveTab(tabName) {{
      activeTab = tabName;
      tabButtons.forEach((button) => {{
        const isActive = button.dataset.tab === tabName;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      }});
      Object.entries(tabPanels).forEach(([name, panel]) => {{
        panel.hidden = name !== tabName;
      }});
    }}

    function renderSystems() {{
      tableBody.innerHTML = "";
      if (!systems.length) {{
        const row = document.createElement("tr");
        row.innerHTML = '<td colspan="9" style="color:#66604f;">No hay conexiones configuradas.</td>';
        tableBody.appendChild(row);
        return;
      }}

      systems.forEach((system, index) => {{
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${{escapeHtml(system.id || "")}}</td>
          <td>${{escapeHtml(system.name || "")}}</td>
          <td>${{escapeHtml(system.type || "")}}</td>
          <td>${{escapeHtml(system.server || "")}}</td>
          <td>${{escapeHtml(system.client || "")}}</td>
          <td>${{escapeHtml(system.language || "")}}</td>
          <td>${{system.verify_ssl ? "Sí" : "No"}}</td>
          <td>${{escapeHtml(system.sap_gui_connection_name || "")}}</td>
          <td>
            <div class="inline-actions">
              <button class="button secondary" type="button" data-action="edit" data-index="${{index}}">Editar</button>
              <button class="button danger" type="button" data-action="delete" data-index="${{index}}">Eliminar</button>
            </div>
          </td>
        `;
        tableBody.appendChild(row);
      }});
    }}

    function renderMcpClients() {{
      mcpClientsTableBody.innerHTML = "";
      if (!mcpClients.length) {{
        const row = document.createElement("tr");
        row.innerHTML = '<td colspan="6" class="subtle">No hay datos de clientes MCP.</td>';
        mcpClientsTableBody.appendChild(row);
        return;
      }}

      mcpClients.forEach((client) => {{
        const row = document.createElement("tr");
        const cliClass = client.cliInstalled ? "ok" : "off";
        const mcpClass = client.mcpState === "match" ? "ok" : (client.mcpState === "mismatch" ? "warn" : "off");
        const actions = (client.actions || []).map((action) => {{
          const label = action === "insert" ? "Insertar" : (action === "adjust" ? "Ajustar" : "Eliminar");
          const buttonClass = action === "delete" ? "danger" : (action === "adjust" ? "warning" : "secondary");
          return `<button class="button ${{buttonClass}}" type="button" data-mcp-action="${{action}}" data-client-id="${{client.id}}">${{label}}</button>`;
        }}).join("");
        row.innerHTML = `
          <td><span class="signal" title="${{escapeHtml(client.cliDetail || "")}}"><span class="signal-dot ${{cliClass}}"></span>${{client.cliInstalled ? "Instalado" : "No detectado"}}</span></td>
          <td><strong>${{escapeHtml(client.name || "")}}</strong></td>
          <td><code>${{escapeHtml(client.path || "")}}</code></td>
          <td><span class="signal"><span class="signal-dot ${{mcpClass}}"></span>${{escapeHtml(client.mcpLabel || "")}}</span></td>
          <td><div class="inline-actions">${{actions}}</div></td>
          <td><span class="info-tip" title="${{escapeHtml(client.detail || "")}}">?</span></td>
        `;
        mcpClientsTableBody.appendChild(row);
      }});
    }}

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function setStatus(text, isError = false) {{
      statusEl.textContent = text;
      statusEl.style.color = isError ? "var(--danger)" : "var(--accent)";
    }}

    async function loadConfig() {{
      setStatus("Cargando configuración...");
      const response = await fetch(configUrl, {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || "No se pudo cargar la configuración.");
      }}
      sapGuiExecutablePathInput.value = payload.sapGuiExecutablePath || "";
      systems.length = 0;
      (payload.systems || []).forEach((system) => systems.push(system));
      renderSystems();
      setStatus("Configuración cargada.");
    }}

    async function loadMcpClients() {{
      const response = await fetch(mcpStatusUrl, {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || "No se pudo cargar el estado MCP.");
      }}
      mcpClients.length = 0;
      (payload.clients || []).forEach((client) => mcpClients.push(client));
      renderMcpClients();
    }}

    async function loadMemoryTree() {{
      const response = await fetch(memoryTreeUrl, {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || "No se pudo cargar el árbol de memoria.");
      }}
      memoryNodes = payload.nodes || [];
      renderMemoryTree();
    }}

    function filterMemoryNodes(nodes, filterText) {{
      const normalized = filterText.trim().toLowerCase();
      if (!normalized) {{
        return nodes;
      }}
      const result = [];
      nodes.forEach((node) => {{
        const nodeName = String(node.name || "").toLowerCase();
        if (node.type === "folder") {{
          const filteredChildren = filterMemoryNodes(node.children || [], normalized);
          if (nodeName.includes(normalized) || filteredChildren.length) {{
            result.push({{ ...node, children: filteredChildren }});
          }}
          return;
        }}
        if (nodeName.includes(normalized) || String(node.relativePath || "").toLowerCase().includes(normalized)) {{
          result.push(node);
        }}
      }});
      return result;
    }}

    function renderMemoryNode(node, forceOpen = false) {{
      if (node.type === "folder") {{
        const wrapper = document.createElement("details");
        wrapper.open = forceOpen;
        const summary = document.createElement("summary");
        summary.textContent = node.name || "(carpeta)";
        wrapper.appendChild(summary);

        const children = document.createElement("div");
        children.className = "children";
        (node.children || []).forEach((child) => children.appendChild(renderMemoryNode(child, forceOpen)));
        wrapper.appendChild(children);
        return wrapper;
      }}

      const button = document.createElement("button");
      button.type = "button";
      button.className = "file-row";
      if (selectedMemoryPath === node.relativePath) {{
        button.classList.add("active");
      }}
      button.dataset.memoryPath = node.relativePath || "";
      button.innerHTML = `${{escapeHtml(node.name || "(fichero)")}}<span class="file-meta">${{escapeHtml(node.extension || "")}}</span>`;
      return button;
    }}

    function renderMemoryTree() {{
      const filtered = filterMemoryNodes(memoryNodes, memoryFilterInput.value || "");
      memoryTreeEl.innerHTML = "";
      if (!filtered.length) {{
        memoryTreeEl.innerHTML = '<div class="subtle">No hay documentos .md o .pdf que coincidan con el filtro.</div>';
        return;
      }}
      filtered.forEach((node) => memoryTreeEl.appendChild(renderMemoryNode(node, Boolean((memoryFilterInput.value || "").trim()))));
    }}

    function showMemoryPlaceholder() {{
      memoryViewerTitleEl.textContent = "Documento";
      memoryViewerMetaEl.textContent = "Selecciona un fichero .md o .pdf";
      memoryViewerEl.innerHTML = '<div class="viewer-placeholder">Selecciona un documento del árbol para verlo aquí.</div>';
    }}

    async function openMemoryDocument(relativePath) {{
      selectedMemoryPath = relativePath;
      renderMemoryTree();
      const extension = String(relativePath.split(".").pop() || "").toLowerCase();
      memoryViewerTitleEl.textContent = relativePath.split("/").pop() || "Documento";
      memoryViewerMetaEl.textContent = relativePath;

      if (extension === "pdf") {{
        memoryViewerEl.innerHTML = `<iframe class="viewer-frame" src="${{memoryDocumentUrl}}?relativePath=${{encodeURIComponent(relativePath)}}"></iframe>`;
        return;
      }}

      const response = await fetch(`${{memoryDocumentUrl}}?relativePath=${{encodeURIComponent(relativePath)}}`, {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || "No se pudo abrir el documento de memoria.");
      }}
      memoryViewerEl.innerHTML = `<div class="markdown-view">${{escapeHtml(payload.content || "")}}</div>`;
    }}

    async function runMcpAction(clientId, action) {{
      const response = await fetch(mcpActionUrl, {{
        method: "POST",
        credentials: "same-origin",
        headers: {{
          "Content-Type": "application/json"
        }},
        body: JSON.stringify({{
          clientId,
          action
        }})
      }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || "No se pudo aplicar la acción MCP.");
      }}
      await loadMcpClients();
      setStatus(payload.message || "Acción MCP aplicada.");
    }}

    function openEditor(index) {{
      editingIndex = index;
      const source = index === null
        ? {{ id: "", name: "", type: "", server: "", user: "", password: "", client: "", language: "EN", verify_ssl: false, sap_gui_connection_name: "" }}
        : systems[index];

      dialogTitle.textContent = index === null ? "Añadir conexión SAP" : "Editar conexión SAP";
      document.getElementById("systemId").value = source.id || "";
      document.getElementById("systemName").value = source.name || "";
      document.getElementById("systemType").value = source.type || "";
      document.getElementById("systemServer").value = source.server || "";
      document.getElementById("systemUser").value = source.user || "";
      document.getElementById("systemPassword").value = source.password || "";
      document.getElementById("systemClient").value = source.client || "";
      document.getElementById("systemLanguage").value = source.language || "EN";
      document.getElementById("verifySsl").checked = Boolean(source.verify_ssl);
      document.getElementById("sapGuiConnectionName").value = source.sap_gui_connection_name || "";
      editorDialog.showModal();
    }}

    function renderSapLogonEntries() {{
      sapLogonTableBody.innerHTML = "";
      if (!sapLogonEntries.length) {{
        const row = document.createElement("tr");
        row.innerHTML = '<td colspan="5" style="color:#66604f;">No se han encontrado entradas de SAP Logon.</td>';
        sapLogonTableBody.appendChild(row);
        return;
      }}

      sapLogonEntries.forEach((entry, index) => {{
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${{escapeHtml(entry.name || "")}}</td>
          <td>${{escapeHtml(entry.systemId || "")}}</td>
          <td>${{escapeHtml(entry.host || "")}}</td>
          <td>${{escapeHtml(entry.port || "")}}</td>
          <td><button class="button secondary" type="button" data-import-index="${{index}}">Usar</button></td>
        `;
        sapLogonTableBody.appendChild(row);
      }});
    }}

    async function loadSapLogonEntries() {{
      const response = await fetch(sapLogonUrl, {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || "No se pudieron cargar las entradas de SAP Logon.");
      }}
      sapLogonEntries = payload.entries || [];
      renderSapLogonEntries();
    }}

    async function importSapLogonEntry(index) {{
      const entry = sapLogonEntries[index];
      if (!entry) {{
        return;
      }}

      document.getElementById("systemId").value = (entry.systemId || document.getElementById("systemId").value || "").toUpperCase();
      document.getElementById("systemName").value = entry.name || document.getElementById("systemName").value || "";
      document.getElementById("sapGuiConnectionName").value = entry.name || document.getElementById("sapGuiConnectionName").value || "";
      sapLogonDialog.close();

      const userValue = document.getElementById("systemUser").value.trim();
      const passwordValue = document.getElementById("systemPassword").value;
      if (sapLogonImportMode !== "auto") {{
        setStatus("Importación básica aplicada desde SAP Logon. La búsqueda automática del puerto se ha omitido porque faltan usuario/password.");
        return;
      }}

      setStatus("Buscando el puerto HTTPS en SAP GUI...");
      try {{
        const response = await fetch(sapLogonImportUrl, {{
          method: "POST",
          credentials: "same-origin",
          headers: {{
            "Content-Type": "application/json"
          }},
          body: JSON.stringify({{
            name: entry.name || "",
            host: entry.host || "",
            systemId: entry.systemId || "",
            client: document.getElementById("systemClient").value.trim(),
            user: userValue,
            password: passwordValue,
            language: document.getElementById("systemLanguage").value.trim() || "EN"
          }})
        }});
        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(payload.message || "No se pudo descubrir el puerto HTTPS automáticamente.");
        }}
        document.getElementById("systemServer").value = payload.server || document.getElementById("systemServer").value || "";
        document.getElementById("sapGuiConnectionName").value = payload.connectionName || document.getElementById("sapGuiConnectionName").value || "";
        if (payload.defaultClient && !document.getElementById("systemClient").value.trim()) {{
          document.getElementById("systemClient").value = payload.defaultClient;
        }}
        setStatus(payload.message || "Importación completada con autodetección del puerto HTTPS.");
      }} catch (error) {{
        console.error(error);
        setStatus(error.message || "No se pudo descubrir el puerto HTTPS automáticamente. Usa la ayuda manual.", true);
      }}
    }}

    function removeSystem(index) {{
      systems.splice(index, 1);
      renderSystems();
      setStatus("Conexión eliminada de la lista. Falta guardar para persistir el cambio.");
    }}

    systemForm.addEventListener("submit", (event) => {{
      event.preventDefault();
      const system = {{
        id: document.getElementById("systemId").value.trim().toUpperCase(),
        name: document.getElementById("systemName").value.trim(),
        type: document.getElementById("systemType").value.trim(),
        server: document.getElementById("systemServer").value.trim(),
        user: document.getElementById("systemUser").value.trim(),
        password: document.getElementById("systemPassword").value,
        client: document.getElementById("systemClient").value.trim(),
        language: document.getElementById("systemLanguage").value.trim() || "EN",
        verify_ssl: document.getElementById("verifySsl").checked,
        sap_gui_connection_name: document.getElementById("sapGuiConnectionName").value.trim(),
      }};

      if (editingIndex === null) {{
        systems.push(system);
      }} else {{
        systems[editingIndex] = system;
      }}
      editorDialog.close();
      renderSystems();
      setStatus("Conexión preparada. Falta guardar para persistir el cambio.");
    }});

    document.getElementById("closeDialogButton").addEventListener("click", () => editorDialog.close());
    document.getElementById("closeSapLogonDialogButton").addEventListener("click", () => sapLogonDialog.close());
    document.getElementById("addSystemButton").addEventListener("click", () => openEditor(null));
    document.getElementById("openPortHelpButton").addEventListener("click", () => {{
      window.open(portHelpUrl, "_blank", "noopener,noreferrer");
    }});
    tabButtons.forEach((button) => {{
      button.addEventListener("click", () => setActiveTab(button.dataset.tab));
    }});
    memoryFilterInput.addEventListener("input", () => renderMemoryTree());
    memoryTreeEl.addEventListener("click", async (event) => {{
      const button = event.target.closest("button[data-memory-path]");
      if (!button) {{
        return;
      }}
      try {{
        await openMemoryDocument(button.dataset.memoryPath || "");
      }} catch (error) {{
        console.error(error);
        setStatus(error.message || "No se pudo abrir el documento de memoria.", true);
      }}
    }});
    document.getElementById("importSapLogonButton").addEventListener("click", async () => {{
      try {{
        const userValue = document.getElementById("systemUser").value.trim();
        const passwordValue = document.getElementById("systemPassword").value;
        sapLogonImportMode = "auto";
        if (!userValue || !passwordValue) {{
          const continueWithoutAuto = window.confirm(
            "Sin usuario y password no se podrá hacer la búsqueda automática del puerto ni capturar el mandante por defecto. " +
            "Pulsa Aceptar para continuar con una importación básica desde SAP Logon o Cancelar para volver y rellenar esos datos."
          );
          if (!continueWithoutAuto) {{
            setStatus("Rellena usuario y password en la conexión y vuelve a lanzar la importación desde SAP Logon.", true);
            return;
          }}
          sapLogonImportMode = "basic";
        }}
        await loadSapLogonEntries();
        sapLogonDialog.showModal();
      }} catch (error) {{
        console.error(error);
        setStatus(error.message || "No se pudieron cargar las entradas de SAP Logon.", true);
      }}
    }});
    tableBody.addEventListener("click", (event) => {{
      const button = event.target.closest("button[data-action]");
      if (!button) {{
        return;
      }}
      const index = Number(button.dataset.index);
      if (button.dataset.action === "edit") {{
        openEditor(index);
      }} else if (button.dataset.action === "delete") {{
        removeSystem(index);
      }}
    }});
    mcpClientsTableBody.addEventListener("click", async (event) => {{
      const button = event.target.closest("button[data-mcp-action]");
      if (!button) {{
        return;
      }}
      try {{
        await runMcpAction(button.dataset.clientId, button.dataset.mcpAction);
      }} catch (error) {{
        console.error(error);
        setStatus(error.message || "No se pudo aplicar la acción MCP.", true);
      }}
    }});
    sapLogonTableBody.addEventListener("click", async (event) => {{
      const button = event.target.closest("button[data-import-index]");
      if (!button) {{
        return;
      }}
      await importSapLogonEntry(Number(button.dataset.importIndex));
    }});

    document.getElementById("saveButton").addEventListener("click", async () => {{
      setStatus("Guardando configuración...");
      const response = await fetch(configUrl, {{
        method: "POST",
        credentials: "same-origin",
        headers: {{
          "Content-Type": "application/json"
        }},
        body: JSON.stringify({{
          sapGuiExecutablePath: sapGuiExecutablePathInput.value.trim(),
          systems
        }})
      }});

      const payload = await response.json();
      if (!response.ok) {{
        setStatus(payload.message || "No se pudo guardar la configuración.", true);
        return;
      }}
      setStatus(payload.message || "Configuración guardada.");
      await loadConfig();
    }});

    showMemoryPlaceholder();
    Promise.all([loadConfig(), loadMcpClients(), loadMemoryTree()]).catch((error) => {{
      console.error(error);
      setStatus(error.message || "No se pudo cargar la configuración.", true);
    }});
  </script>
</body>
</html>"""


mcp = FastMCP(name="ABAP Tools - MCP Server", version="1.0.0", lifespan=abap_lifespan)
print("FastMCP server object created.")


@mcp.custom_route(HTTP_DASHBOARD_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_page(_request):
    """Serve the lightweight dashboard used to manage SAP systems in the .env file."""
    return HTMLResponse(_dashboard_html())


@mcp.custom_route(HTTP_DASHBOARD_CONFIG_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_config(_request):
    """Return the dashboard-managed SAP configuration as JSON."""
    try:
        return JSONResponse(get_dashboard_config())
    except Exception as exc:
        return JSONResponse({"message": f"Failed to load dashboard configuration: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MCP_STATUS_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_mcp_status(_request):
    """Return the MCP client status table shown in the dashboard."""
    try:
        return JSONResponse(dashboard_get_mcp_status_data())
    except Exception as exc:
        return JSONResponse({"message": f"Failed to load MCP client status: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MCP_ACTION_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_apply_mcp_action_route(request):
    """Insert, adjust or delete the ABAP MCP entry in one local client configuration."""
    try:
        payload = await request.json()
        client_id = str(payload.get("clientId", "") or "").strip().lower()
        action = str(payload.get("action", "") or "").strip().lower()
        return JSONResponse(dashboard_apply_mcp_action(client_id, action))
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"message": f"Failed to apply MCP dashboard action: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MEMORY_TREE_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_memory_tree(_request):
    """Return the local documents tree shown in the dashboard memory tab."""
    try:
        return JSONResponse(_memory_tree_payload())
    except Exception as exc:
        return JSONResponse({"message": f"Failed to load memory tree: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MEMORY_DOCUMENT_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_memory_document(request):
    """Return one local memory document either as markdown JSON or as a PDF file response."""
    try:
        relative_path = str(request.query_params.get("relativePath", "") or "").strip()
        _, target_path = _resolve_memory_relative_path(relative_path)
        if target_path.suffix.lower() == ".pdf":
            if not target_path.exists():
                raise FileNotFoundError(f"The memory document '{relative_path}' does not exist.")
            return FileResponse(target_path, media_type="application/pdf", filename=target_path.name)
        return JSONResponse(_load_memory_markdown(relative_path))
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except FileNotFoundError as exc:
        return JSONResponse({"message": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"message": f"Failed to load memory document: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_PORT_HELP_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_port_help_page(_request):
    """Serve the SAP GUI tutorial showing how to find the HTTPS port in SMICM."""
    return HTMLResponse(render_dashboard_port_help_html())


@mcp.custom_route(HTTP_DASHBOARD_CONFIG_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_save_config(request):
    """Persist the dashboard-managed SAP configuration back into the .env file."""
    try:
        payload = await request.json()
        systems = payload.get("systems", [])
        sap_gui_executable_path = str(payload.get("sapGuiExecutablePath", "") or "")
        update_dashboard_config(systems, sap_gui_executable_path)
        return JSONResponse({"message": "Dashboard configuration saved successfully."})
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"message": f"Failed to save dashboard configuration: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_SAPLOGON_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_list_saplogon_entries(_request):
    """Return the SAP Logon entries discovered from the local SAP UI Landscape XML files."""
    try:
        return JSONResponse(list_sap_logon_entries())
    except Exception as exc:
        return JSONResponse({"message": f"Failed to load SAP Logon entries: {str(exc)}"}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_import_saplogon_entry(request):
    """Resolve the HTTPS endpoint for one SAP Logon entry through a temporary SAP GUI session."""
    try:
        payload = await request.json()
        connection_name = str(payload.get("name", "") or "").strip()
        host = str(payload.get("host", "") or "").strip()
        result = await asyncio.to_thread(
            discover_sap_logon_https_endpoint_subprocess,
            connection_name,
            host,
            system_id=str(payload.get("systemId", "") or "").strip(),
            client=str(payload.get("client", "") or "").strip(),
            user=str(payload.get("user", "") or "").strip(),
            password=str(payload.get("password", "") or ""),
            language=str(payload.get("language", "") or "EN").strip() or "EN",
        )
        protocol = str(result.get("protocol", "") or "").strip().lower()
        protocol_label = "HTTPS" if protocol == "https" else "HTTP"
        message = f"Puerto {protocol_label} detectado automáticamente para {connection_name}: {result['server']}"
        used_connection_name = str(result.get("connectionName", "") or "").strip()
        if used_connection_name and used_connection_name != connection_name:
            message += f". Se ha utilizado la entrada SAP GUI '{used_connection_name}' porque la seleccionada no se podía abrir automáticamente."
        default_client = str(result.get("defaultClient", "") or "").strip()
        if default_client:
            message += f". Mandante detectado: {default_client}."
        return JSONResponse({
            **result,
            "message": message,
        })
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"message": str(exc)}, status_code=409)
    except Exception as exc:
        return JSONResponse({"message": f"Failed to import the SAP Logon entry automatically: {str(exc)}"}, status_code=500)


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def root_redirect(_request):
    """Redirect the root page to the dashboard when the server runs over HTTP."""
    return RedirectResponse(url=HTTP_DASHBOARD_PATH, status_code=307)

# region Systems
@mcp.tool()
def sap_systems_list() -> SapSystemListResponse:
    """List the SAP systems configured in the MCP server, including their ids, names, and environment types."""
    return call_sap_systems_list()
# endregion

#region Login/Logout
@mcp.tool()
def login(
    systemId: str = Field(..., description="Identifier of the configured SAP system to log in to. Use sap_systems_list first if you need to discover the available systems.")
) -> LoginResponse:
    """Open an authenticated ADT session for one configured SAP system and fetch its CSRF token.

    Call this before using tools that read or change SAP objects in that system."""
    return call_login(systemId)

@mcp.tool()
def logout(
    systemId: str = Field(..., description="Identifier of the configured SAP system whose session should be closed.")
) -> LogoutResponse:
    """Close the SAP session for one configured system and clear its stored CSRF token."""
    return call_logout(systemId)
#endregion

# region SAP GUI
@mcp.tool()
def sap_gui_sessions_list() -> SapGuiSessionListResponse:
    """List the SAP GUI scripting sessions currently registered in the MCP server."""
    return call_sap_gui_sessions_list()


@mcp.tool()
def sap_gui_session_open(
    systemId: str = Field(..., description="Identifier of the configured SAP system whose SAP GUI connection should be opened. The system must define sap_gui_connection_name in the MCP configuration.")
) -> SapGuiSessionOpenResponse:
    """Open one new SAP GUI scripting session for a configured SAP system using its SAP Logon connection name from the MCP configuration."""
    return call_sap_gui_session_open(systemId)


@mcp.tool()
def sap_gui_session_close(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open.")
) -> SapGuiSessionCloseResponse:
    """Close one previously opened SAP GUI scripting session."""
    return call_sap_gui_session_close(guiSessionId)


@mcp.tool()
def sap_gui_session_screenshot(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open."),
    filePath: str = Field(..., description="Absolute local file path where the screenshot should be written."),
    windowId: str = Field("", description="Optional SAP GUI wnd id to capture, for example wnd[1]. Leave empty to use the main window unless allWindows is true."),
    allWindows: bool = Field(False, description="When true, capture all available SAP GUI wnd[*] windows and compose them into one screenshot using the same layout style as the recording screenshots."),
) -> SapGuiSessionScreenshotResponse:
    """Capture one SAP GUI window or compose all visible windows for one registered session and store the result in a local file."""
    return call_sap_gui_session_screenshot(guiSessionId, filePath, windowId, allWindows)


@mcp.tool()
def sap_gui_session_inspect(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open."),
    maxDepth: int = Field(4, description="Maximum control-tree depth to inspect. Use lower values for smaller responses and higher values when more nested SAP GUI controls are needed.")
) -> SapGuiSessionInspectResponse:
    """Inspect one registered SAP GUI session and return a structured tree of SAP GUI controls, including ids, types, text, tooltips, and child controls."""
    return call_sap_gui_session_inspect(guiSessionId, maxDepth)


@mcp.tool()
def sap_gui_session_inspect_to_file(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open."),
    filePath: str = Field(..., description="Absolute local file path where the SAP GUI inspection JSON should be written."),
    maxDepth: int = Field(0, description="Maximum control-tree depth to inspect. Use 0 to export the complete tree without a practical depth limit.")
) -> FileTransferResponse:
    """Inspect one registered SAP GUI session and write the structured control tree to a local JSON file. Use this when the inspection result may be too large for a regular MCP response."""
    return call_sap_gui_session_inspect_to_file(guiSessionId, filePath, maxDepth)


@mcp.tool()
def sap_gui_session_read_message(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open.")
) -> SapGuiSessionReadMessageResponse:
    """Read the message currently visible in SAP GUI, prioritizing an active popup and otherwise falling back to the main status bar."""
    return call_sap_gui_session_read_message(guiSessionId)


@mcp.tool()
def sap_gui_session_actions(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open."),
    request: SapGuiSessionActionsRequest = Field(..., description="Ordered SAP GUI actions to execute. Use a single action for simple interactions or multiple actions to fill a full screen before continuing. The tool waits only once at the end unless waitForCompletion is set to false.")
) -> SapGuiSessionActionsResponse:
    """Execute one or more SAP GUI actions against a registered session and, by default, wait only once at the end until SAP GUI has finished reacting."""
    return call_sap_gui_session_actions(guiSessionId, request)


@mcp.tool()
def sap_gui_recording_start(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open."),
    folderPath: str = Field(..., description="Absolute local folder path where SAP GUI recording artifacts should be written. The tool will create the folder if it does not exist.")
) -> SapGuiRecordingStartResponse:
    """Start SAP GUI native recording for one registered session and direct the recording output to a local folder. The folder will contain `recording.vbs`, `metadata.json`, logs, and captured screenshots."""
    return call_sap_gui_recording_start(guiSessionId, folderPath)


@mcp.tool()
def sap_gui_recording_stop(
    guiSessionId: str = Field(..., description="Internal SAP GUI scripting session identifier returned by sap_gui_session_open.")
) -> SapGuiRecordingStopResponse:
    """Stop SAP GUI native recording for one registered session and return the paths of the generated recording artifacts."""
    return call_sap_gui_recording_stop(guiSessionId)
# endregion

# region Knowledge
@mcp.tool()
def knowledge_upsert_document(
    request: KnowledgeUpsertDocumentRequest = Field(..., description="Knowledge document to insert or update inside the local repository rooted at db/documents. The relative path must stay inside that fixed documents folder.")
) -> KnowledgeUpsertDocumentResponse:
    """Insert or update one knowledge document in db/documents and reindex it into the local Chroma collection."""
    return call_knowledge_upsert_document(request)


@mcp.tool()
def knowledge_search(
    query: str = Field(..., description="Semantic search query used to retrieve relevant chunks from the local knowledge base."),
    limit: int = Field(5, description="Maximum number of matching chunks to return.")
) -> KnowledgeSearchResponse:
    """Search the local knowledge base semantically through the fixed Chroma collection stored under db/chroma."""
    return call_knowledge_search(query, limit)


@mcp.tool()
def knowledge_get_document(
    relativePath: str = Field(..., description="Relative path of the stored document inside db/documents. Do not include the fixed documents root.")
) -> KnowledgeGetDocumentResponse:
    """Load one previously stored knowledge document together with its metadata from db/documents."""
    return call_knowledge_get_document(relativePath)
# endregion

# region Program Includes
@mcp.tool()
def source_program_include_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include will be created."),
    request: IncludeCreateRequest = Field(..., description="Metadata of the ABAP include to create, including name, description and package."),
    transportNumber: str = Field("", description="Transport request number to forward when the include belongs to a transportable package.")
) -> IncludeCreateResponse:
    """Create one ABAP include through the ADT includes collection endpoint."""
    return call_include_create(systemId, request, transportNumber)


@mcp.tool()
def source_program_include_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include source should be read."),
    name: str = Field(..., description="Technical ABAP include name to read.")
) -> IncludeReadResponse:
    """Read the raw source code of one ABAP include from its `/source/main` endpoint."""
    return call_include_read(systemId, name)


@mcp.tool()
def source_program_include_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include should be locked."),
    name: str = Field(..., description="Technical ABAP include name to lock.")
) -> IncludeLockResponse:
    """Lock one ABAP include through the ADT lock action and return the lock handle required for raw source updates."""
    return call_include_lock(systemId, name)


@mcp.tool()
def source_program_include_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include should be unlocked."),
    name: str = Field(..., description="Technical ABAP include name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by source_program_include_lock.")
) -> IncludeLockResponse:
    """Unlock one ABAP include through the ADT unlock action using a previously returned lock handle."""
    return call_include_unlock(systemId, name, lockHandle)


@mcp.tool()
def source_program_include_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include source should be updated."),
    name: str = Field(..., description="Technical ABAP include name to update."),
    request: IncludeUpdateRequest = Field(..., description="Full ABAP source code to store in the include source."),
    transportNumber: str = Field("", description="Transport request number to forward when the include belongs to a transportable package.")
) -> IncludeUpdateResponse:
    """Update the raw source code of one ABAP include through its `/source/main` endpoint. The tool locks the include, writes the new source, and unlocks it automatically."""
    lock_response = call_include_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return IncludeUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the include.",
            "data": None
        })

    try:
        return call_include_update(systemId, name, lock_response.data.lockHandle, request, transportNumber)
    finally:
        call_include_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def source_program_include_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include will be deleted."),
    name: str = Field(..., description="Technical ABAP include name to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete one ABAP include through the generic ADT deletion endpoint using the repository object URI."""
    return call_include_delete(systemId, name, transportNumber)


@mcp.tool()
def source_program_include_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include source should be read."),
    name: str = Field(..., description="Technical ABAP include name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written.")
) -> FileTransferResponse:
    """Download the raw source code of one ABAP include to a local file from its `/source/main` endpoint."""
    return call_include_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_program_include_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP include source should be updated."),
    name: str = Field(..., description="Technical ABAP include name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
    transportNumber: str = Field("", description="Transport request number to forward when the include belongs to a transportable package.")
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing include through its `/source/main` endpoint. The tool locks the include, writes the new source, and unlocks it automatically."""
    return call_include_write_from_file(systemId, name, filePath, transportNumber)
# endregion

# region Function Group Includes
@mcp.tool()
def source_function_include_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include will be created."),
    request: FunctionIncludeCreateRequest = Field(..., description="Metadata of the function group include to create, including its name, description and parent function group."),
) -> FunctionIncludeCreateResponse:
    """Create one function group include through the ADT includes collection endpoint below its parent function group."""
    return call_function_include_create(systemId, request)


@mcp.tool()
def source_function_include_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include source should be read."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to read.")
) -> FunctionIncludeReadResponse:
    """Read the raw source code of one function group include from its `/source/main` endpoint."""
    return call_function_include_read(systemId, functionGroupName, name)


@mcp.tool()
def source_function_include_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include should be locked."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to lock.")
) -> FunctionIncludeLockResponse:
    """Lock one function group include through the ADT lock action and return the lock handle required for raw source updates."""
    return call_function_include_lock(systemId, functionGroupName, name)


@mcp.tool()
def source_function_include_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include should be unlocked."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by source_function_include_lock.")
) -> FunctionIncludeLockResponse:
    """Unlock one function group include through the ADT unlock action using a previously returned lock handle."""
    return call_function_include_unlock(systemId, functionGroupName, name, lockHandle)


@mcp.tool()
def source_function_include_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include source should be updated."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to update."),
    request: FunctionIncludeUpdateRequest = Field(..., description="Full ABAP source code to store in the include source."),
) -> FunctionIncludeUpdateResponse:
    """Update the raw source code of one function group include through its `/source/main` endpoint. The tool locks the include, writes the new source, and unlocks it automatically."""
    lock_response = call_function_include_lock(systemId, functionGroupName, name)
    if not lock_response.result or not lock_response.data:
        return FunctionIncludeUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the function group include.",
            "data": None
        })

    try:
        return call_function_include_update(systemId, functionGroupName, name, lock_response.data.lockHandle, request)
    finally:
        call_function_include_unlock(systemId, functionGroupName, name, lock_response.data.lockHandle)


@mcp.tool()
def source_function_include_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include will be deleted."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to delete."),
) -> DeletionDeleteResponse:
    """Delete one function group include through the generic ADT deletion endpoint using the repository object URI."""
    return call_function_include_delete(systemId, functionGroupName, name)


@mcp.tool()
def source_function_include_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include source should be read."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written."),
) -> FileTransferResponse:
    """Download the raw source code of one function group include to a local file from its `/source/main` endpoint."""
    return call_function_include_read_to_file(systemId, functionGroupName, name, filePath)


@mcp.tool()
def source_function_include_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group include source should be updated."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include."),
    name: str = Field(..., description="Technical ABAP function group include name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing function group include through its `/source/main` endpoint. The tool locks the include, writes the new source, and unlocks it automatically."""
    return call_function_include_write_from_file(systemId, functionGroupName, name, filePath)
# endregion

# region Function Modules
@mcp.tool()
def source_function_module_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module will be created."),
    request: FunctionModuleCreateRequest = Field(..., description="Metadata of the ABAP function module to create, including its name, description and parent function group."),
) -> FunctionModuleCreateResponse:
    """Create one ABAP function module through the ADT function modules collection endpoint below its parent function group."""
    return call_function_module_create(systemId, request)


@mcp.tool()
def source_function_module_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module source should be read."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to read.")
) -> FunctionModuleReadResponse:
    """Read the raw source code of one ABAP function module from its `/source/main` endpoint."""
    return call_function_module_read(systemId, functionGroupName, name)


@mcp.tool()
def source_function_module_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module should be locked."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to lock.")
) -> FunctionModuleLockResponse:
    """Lock one ABAP function module through the ADT lock action and return the lock handle required for raw source updates."""
    return call_function_module_lock(systemId, functionGroupName, name)


@mcp.tool()
def source_function_module_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module should be unlocked."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by source_function_module_lock.")
) -> FunctionModuleLockResponse:
    """Unlock one ABAP function module through the ADT unlock action using a previously returned lock handle."""
    return call_function_module_unlock(systemId, functionGroupName, name, lockHandle)


@mcp.tool()
def source_function_module_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module source should be updated."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to update."),
    request: FunctionModuleUpdateRequest = Field(..., description="Full ABAP source code to store in the function module source."),
) -> FunctionModuleUpdateResponse:
    """Update the raw source code of one ABAP function module through its `/source/main` endpoint. The tool locks the function module, writes the new source, and unlocks it automatically."""
    lock_response = call_function_module_lock(systemId, functionGroupName, name)
    if not lock_response.result or not lock_response.data:
        return FunctionModuleUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the function module.",
            "data": None
        })

    try:
        return call_function_module_update(systemId, functionGroupName, name, lock_response.data.lockHandle, request)
    finally:
        call_function_module_unlock(systemId, functionGroupName, name, lock_response.data.lockHandle)


@mcp.tool()
def source_function_module_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module will be deleted."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to delete."),
) -> DeletionDeleteResponse:
    """Delete one ABAP function module through the generic ADT deletion endpoint using the repository object URI."""
    return call_function_module_delete(systemId, functionGroupName, name)


@mcp.tool()
def source_function_module_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module source should be read."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written."),
) -> FileTransferResponse:
    """Download the raw source code of one ABAP function module to a local file from its `/source/main` endpoint."""
    return call_function_module_read_to_file(systemId, functionGroupName, name, filePath)


@mcp.tool()
def source_function_module_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function module source should be updated."),
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module."),
    name: str = Field(..., description="Technical ABAP function module name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing function module through its `/source/main` endpoint. The tool locks the function module, writes the new source, and unlocks it automatically."""
    return call_function_module_write_from_file(systemId, functionGroupName, name, filePath)
# endregion

# region Function Groups
@mcp.tool()
def source_function_group_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group will be created."),
    request: FunctionGroupCreateRequest = Field(..., description="Metadata of the ABAP function group to create, including name, description and package."),
    transportNumber: str = Field("", description="Transport request number to forward when the function group belongs to a transportable package.")
) -> FunctionGroupCreateResponse:
    """Create one ABAP function group through the ADT function groups collection endpoint."""
    return call_function_group_create(systemId, request, transportNumber)


@mcp.tool()
def source_function_group_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group source should be read."),
    name: str = Field(..., description="Technical ABAP function group name to read.")
) -> FunctionGroupReadResponse:
    """Read the raw source code of one ABAP function group from its `/source/main` endpoint."""
    return call_function_group_read(systemId, name)


@mcp.tool()
def source_function_group_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group should be locked."),
    name: str = Field(..., description="Technical ABAP function group name to lock.")
) -> FunctionGroupLockResponse:
    """Lock one ABAP function group through the ADT lock action and return the lock handle required for raw source updates."""
    return call_function_group_lock(systemId, name)


@mcp.tool()
def source_function_group_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group should be unlocked."),
    name: str = Field(..., description="Technical ABAP function group name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by source_function_group_lock.")
) -> FunctionGroupLockResponse:
    """Unlock one ABAP function group through the ADT unlock action using a previously returned lock handle."""
    return call_function_group_unlock(systemId, name, lockHandle)


@mcp.tool()
def source_function_group_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group source should be updated."),
    name: str = Field(..., description="Technical ABAP function group name to update."),
    request: FunctionGroupUpdateRequest = Field(..., description="Full ABAP source code to store in the function group source."),
    transportNumber: str = Field("", description="Transport request number to forward when the function group belongs to a transportable package.")
) -> FunctionGroupUpdateResponse:
    """Update the raw source code of one ABAP function group through its `/source/main` endpoint. The tool locks the function group, writes the new source, and unlocks it automatically."""
    lock_response = call_function_group_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return FunctionGroupUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the function group.",
            "data": None
        })

    try:
        return call_function_group_update(systemId, name, lock_response.data.lockHandle, request, transportNumber)
    finally:
        call_function_group_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def source_function_group_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group will be deleted."),
    name: str = Field(..., description="Technical ABAP function group name to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete one ABAP function group through the generic ADT deletion endpoint using the repository object URI."""
    return call_function_group_delete(systemId, name, transportNumber)


@mcp.tool()
def source_function_group_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group source should be read."),
    name: str = Field(..., description="Technical ABAP function group name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written.")
) -> FileTransferResponse:
    """Download the raw source code of one ABAP function group to a local file from its `/source/main` endpoint."""
    return call_function_group_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_function_group_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP function group source should be updated."),
    name: str = Field(..., description="Technical ABAP function group name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
    transportNumber: str = Field("", description="Transport request number to forward when the function group belongs to a transportable package.")
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing function group through its `/source/main` endpoint. The tool locks the function group, writes the new source, and unlocks it automatically."""
    return call_function_group_write_from_file(systemId, name, filePath, transportNumber)


@mcp.tool()
def source_function_group_symbols_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group text symbols should be read."),
    name: str = Field(..., description="Technical ABAP function group name whose text symbols should be read."),
) -> SourceSymbolsReadResponse:
    """Read the text symbols of one ABAP function group from its `/source/symbols` endpoint."""
    return call_function_group_symbols_read(systemId, name)


@mcp.tool()
def source_function_group_symbols_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group text symbols should be updated."),
    name: str = Field(..., description="Technical ABAP function group name whose text symbols should be updated."),
    request: SourceSymbolsUpdateRequest = Field(..., description="Full text symbols content to store in the function group symbols resource."),
) -> SourceSymbolsUpdateResponse:
    """Update the text symbols of one ABAP function group through its `/source/symbols` endpoint. The tool locks the function group, writes the new symbols, and unlocks it automatically."""
    return call_function_group_symbols_update(systemId, name, request)


@mcp.tool()
def source_function_group_symbols_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group text symbols should be read."),
    name: str = Field(..., description="Technical ABAP function group name whose text symbols should be read."),
    filePath: str = Field(..., description="Absolute local file path where the raw text symbols should be written."),
) -> FileTransferResponse:
    """Download the text symbols of one ABAP function group to a local file from its `/source/symbols` endpoint."""
    return call_function_group_symbols_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_function_group_symbols_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the function group text symbols should be updated."),
    name: str = Field(..., description="Technical ABAP function group name whose text symbols should be updated."),
    filePath: str = Field(..., description="Absolute local file path of the raw text symbols to upload."),
) -> FileTransferResponse:
    """Upload text symbols from a local file to one existing ABAP function group through its `/source/symbols` endpoint. The tool locks the function group, writes the new symbols, and unlocks it automatically."""
    return call_function_group_symbols_write_from_file(systemId, name, filePath)
# endregion

# region Interfaces
@mcp.tool()
def source_interface_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface will be created."),
    request: InterfaceCreateRequest = Field(..., description="Metadata of the ABAP interface to create, including name, description and package."),
    transportNumber: str = Field("", description="Transport request number to forward when the interface belongs to a transportable package.")
) -> InterfaceCreateResponse:
    """Create one ABAP interface through the ADT interfaces collection endpoint."""
    return call_interface_create(systemId, request, transportNumber)


@mcp.tool()
def source_interface_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface source should be read."),
    name: str = Field(..., description="Technical ABAP interface name to read.")
) -> InterfaceReadResponse:
    """Read the raw source code of one ABAP interface from its `/source/main` endpoint."""
    return call_interface_read(systemId, name)


@mcp.tool()
def source_interface_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface should be locked."),
    name: str = Field(..., description="Technical ABAP interface name to lock.")
) -> InterfaceLockResponse:
    """Lock one ABAP interface through the ADT lock action and return the lock handle required for raw source updates."""
    return call_interface_lock(systemId, name)


@mcp.tool()
def source_interface_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface should be unlocked."),
    name: str = Field(..., description="Technical ABAP interface name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by interface_lock.")
) -> InterfaceLockResponse:
    """Unlock one ABAP interface through the ADT unlock action using a previously returned lock handle."""
    return call_interface_unlock(systemId, name, lockHandle)


@mcp.tool()
def source_interface_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface source should be updated."),
    name: str = Field(..., description="Technical ABAP interface name to update."),
    request: InterfaceUpdateRequest = Field(..., description="Full ABAP source code to store in the interface source."),
    transportNumber: str = Field("", description="Transport request number to forward when the interface belongs to a transportable package.")
) -> InterfaceUpdateResponse:
    """Update the raw source code of one ABAP interface through its `/source/main` endpoint. The tool locks the interface, writes the new source, and unlocks it automatically."""
    lock_response = call_interface_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return InterfaceUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the interface.",
            "data": None
        })

    try:
        return call_interface_update(systemId, name, lock_response.data.lockHandle, request, transportNumber)
    finally:
        call_interface_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def source_interface_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface will be deleted."),
    name: str = Field(..., description="Technical ABAP interface name to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete one ABAP interface through the generic ADT deletion endpoint using the repository object URI."""
    return call_interface_delete(systemId, name, transportNumber)


@mcp.tool()
def source_interface_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface source should be read."),
    name: str = Field(..., description="Technical ABAP interface name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written.")
) -> FileTransferResponse:
    """Download the raw source code of one ABAP interface to a local file from its `/source/main` endpoint."""
    return call_interface_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_interface_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP interface source should be updated."),
    name: str = Field(..., description="Technical ABAP interface name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
    transportNumber: str = Field("", description="Transport request number to forward when the interface belongs to a transportable package.")
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing interface through its `/source/main` endpoint. The tool locks the interface, writes the new source, and unlocks it automatically."""
    return call_interface_write_from_file(systemId, name, filePath, transportNumber)
# endregion

# region Classes
@mcp.tool()
def source_class_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class will be created."),
    request: ClassCreateRequest = Field(..., description="Metadata of the ABAP class to create, including name, description, package, visibility and optional superclass."),
    transportNumber: str = Field("", description="Transport request number to forward when the class belongs to a transportable package.")
) -> ClassCreateResponse:
    """Create one ABAP class through the ADT classes collection endpoint."""
    return call_class_create(systemId, request, transportNumber)


@mcp.tool()
def source_class_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class source should be read."),
    name: str = Field(..., description="Technical ABAP class name to read.")
) -> ClassReadResponse:
    """Read the raw source code of one ABAP class from its `/source/main` endpoint."""
    return call_class_read(systemId, name)


@mcp.tool()
def source_class_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class should be locked."),
    name: str = Field(..., description="Technical ABAP class name to lock.")
) -> ClassLockResponse:
    """Lock one ABAP class through the ADT lock action and return the lock handle required for raw source updates."""
    return call_class_lock(systemId, name)


@mcp.tool()
def source_class_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class should be unlocked."),
    name: str = Field(..., description="Technical ABAP class name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by class_lock.")
) -> ClassLockResponse:
    """Unlock one ABAP class through the ADT unlock action using a previously returned lock handle."""
    return call_class_unlock(systemId, name, lockHandle)


@mcp.tool()
def source_class_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class source should be updated."),
    name: str = Field(..., description="Technical ABAP class name to update."),
    request: ClassUpdateRequest = Field(..., description="Full ABAP source code to store in the class source."),
    transportNumber: str = Field("", description="Transport request number to forward when the class belongs to a transportable package.")
) -> ClassUpdateResponse:
    """Update the raw source code of one ABAP class through its `/source/main` endpoint. The tool locks the class, writes the new source, and unlocks it automatically."""
    lock_response = call_class_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return ClassUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the class.",
            "data": None
        })

    try:
        return call_class_update(systemId, name, lock_response.data.lockHandle, request, transportNumber)
    finally:
        call_class_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def source_class_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class will be deleted."),
    name: str = Field(..., description="Technical ABAP class name to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete one ABAP class through the generic ADT deletion endpoint using the repository object URI."""
    return call_class_delete(systemId, name, transportNumber)


@mcp.tool()
def source_class_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class source should be read."),
    name: str = Field(..., description="Technical ABAP class name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written.")
) -> FileTransferResponse:
    """Download the raw source code of one ABAP class to a local file from its `/source/main` endpoint."""
    return call_class_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_class_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class source should be updated."),
    name: str = Field(..., description="Technical ABAP class name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
    transportNumber: str = Field("", description="Transport request number to forward when the class belongs to a transportable package.")
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing class through its `/source/main` endpoint. The tool locks the class, writes the new source, and unlocks it automatically."""
    return call_class_write_from_file(systemId, name, filePath, transportNumber)


@mcp.tool()
def source_class_symbols_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class text symbols should be read."),
    name: str = Field(..., description="Technical ABAP class name whose text symbols should be read."),
) -> SourceSymbolsReadResponse:
    """Read the text symbols of one ABAP class from its `/source/symbols` endpoint."""
    return call_class_symbols_read(systemId, name)


@mcp.tool()
def source_class_symbols_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class text symbols should be updated."),
    name: str = Field(..., description="Technical ABAP class name whose text symbols should be updated."),
    request: SourceSymbolsUpdateRequest = Field(..., description="Full text symbols content to store in the class symbols resource."),
) -> SourceSymbolsUpdateResponse:
    """Update the text symbols of one ABAP class through its `/source/symbols` endpoint. The tool locks the class, writes the new symbols, and unlocks it automatically."""
    return call_class_symbols_update(systemId, name, request)


@mcp.tool()
def source_class_symbols_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class text symbols should be read."),
    name: str = Field(..., description="Technical ABAP class name whose text symbols should be read."),
    filePath: str = Field(..., description="Absolute local file path where the raw text symbols should be written."),
) -> FileTransferResponse:
    """Download the text symbols of one ABAP class to a local file from its `/source/symbols` endpoint."""
    return call_class_symbols_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_class_symbols_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class text symbols should be updated."),
    name: str = Field(..., description="Technical ABAP class name whose text symbols should be updated."),
    filePath: str = Field(..., description="Absolute local file path of the raw text symbols to upload."),
) -> FileTransferResponse:
    """Upload text symbols from a local file to one existing ABAP class through its `/source/symbols` endpoint. The tool locks the class, writes the new symbols, and unlocks it automatically."""
    return call_class_symbols_write_from_file(systemId, name, filePath)


@mcp.tool()
def source_class_testclasses_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be created."),
    className: str = Field(..., description="Technical ABAP class name that will own the testclasses include."),
) -> ClassTestclassesCreateResponse:
    """Create the `testclasses` include of one existing ABAP class. The tool locks the class, creates the include, and unlocks it automatically."""
    return call_class_testclasses_create(systemId, className)


@mcp.tool()
def source_class_testclasses_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be read."),
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include."),
) -> ClassTestclassesReadResponse:
    """Read the raw source code of the `testclasses` include of one ABAP class from its direct include resource."""
    return call_class_testclasses_read(systemId, className)


@mcp.tool()
def source_class_testclasses_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be updated."),
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include."),
    request: ClassTestclassesUpdateRequest = Field(..., description="Full ABAP source code to store in the `testclasses` include."),
) -> ClassTestclassesUpdateResponse:
    """Update the raw source code of the `testclasses` include of one ABAP class. The tool locks the class, writes the new source, and unlocks it automatically."""
    return call_class_testclasses_update(systemId, className, request)


@mcp.tool()
def source_class_testclasses_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be read."),
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written."),
) -> FileTransferResponse:
    """Download the `testclasses` include of one ABAP class to a local file from its direct include resource."""
    return call_class_testclasses_read_to_file(systemId, className, filePath)


@mcp.tool()
def source_class_testclasses_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be updated."),
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
) -> FileTransferResponse:
    """Upload the `testclasses` include of one ABAP class from a local file. The tool locks the class, writes the new source, and unlocks it automatically."""
    return call_class_testclasses_write_from_file(systemId, className, filePath)
# endregion

# region Programs
@mcp.tool()
def source_program_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program will be created."),
    request: ProgramCreateRequest = Field(..., description="Metadata of the ABAP program to create, including name, description and package."),
    transportNumber: str = Field("", description="Transport request number to forward when the program belongs to a transportable package.")
) -> ProgramCreateResponse:
    """Create one ABAP program through the ADT programs collection endpoint. Unlike generic source editing, creation uses a dedicated metadata endpoint and does not start from `/source/main`."""
    return call_program_create(systemId, request, transportNumber)


@mcp.tool()
def source_program_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program source should be read."),
    name: str = Field(..., description="Technical ABAP program name to read.")
) -> ProgramReadResponse:
    """Read the raw source code of one ABAP program from its `/source/main` endpoint."""
    return call_program_read(systemId, name)


@mcp.tool()
def source_program_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program should be locked."),
    name: str = Field(..., description="Technical ABAP program name to lock.")
) -> ProgramLockResponse:
    """Lock one ABAP program through the ADT lock action and return the lock handle required for raw source updates."""
    return call_program_lock(systemId, name)


@mcp.tool()
def source_program_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program should be unlocked."),
    name: str = Field(..., description="Technical ABAP program name to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by program_lock.")
) -> ProgramLockResponse:
    """Unlock one ABAP program through the ADT unlock action using a previously returned lock handle."""
    return call_program_unlock(systemId, name, lockHandle)


@mcp.tool()
def source_program_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program source should be updated."),
    name: str = Field(..., description="Technical ABAP program name to update."),
    request: ProgramUpdateRequest = Field(..., description="Full ABAP source code to store in the program source."),
    transportNumber: str = Field("", description="Transport request number to forward when the program belongs to a transportable package.")
) -> ProgramUpdateResponse:
    """Update the raw source code of one ABAP program through its `/source/main` endpoint. The tool locks the program, writes the new source, and unlocks it automatically."""
    lock_response = call_program_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return ProgramUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the program.",
            "data": None
        })

    try:
        return call_program_update(systemId, name, lock_response.data.lockHandle, request, transportNumber)
    finally:
        call_program_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def source_program_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program will be deleted."),
    name: str = Field(..., description="Technical ABAP program name to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete one ABAP program through the generic ADT deletion endpoint using the repository object URI."""
    return call_program_delete(systemId, name, transportNumber)


@mcp.tool()
def source_program_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program source should be read."),
    name: str = Field(..., description="Technical ABAP program name to read."),
    filePath: str = Field(..., description="Absolute local file path where the raw source code should be written.")
) -> FileTransferResponse:
    """Download the raw source code of one ABAP program to a local file from its `/source/main` endpoint."""
    return call_program_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_program_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program source should be updated."),
    name: str = Field(..., description="Technical ABAP program name to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
    transportNumber: str = Field("", description="Transport request number to forward when the program belongs to a transportable package.")
) -> FileTransferResponse:
    """Upload raw ABAP source code from a local file to one existing program through its `/source/main` endpoint. The tool locks the program, writes the new source, and unlocks it automatically."""
    return call_program_write_from_file(systemId, name, filePath, transportNumber)


@mcp.tool()
def source_program_symbols_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program text symbols should be read."),
    name: str = Field(..., description="Technical ABAP program name whose text symbols should be read."),
) -> SourceSymbolsReadResponse:
    """Read the text symbols of one ABAP program from its `/source/symbols` endpoint."""
    return call_program_symbols_read(systemId, name)


@mcp.tool()
def source_program_symbols_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program text symbols should be updated."),
    name: str = Field(..., description="Technical ABAP program name whose text symbols should be updated."),
    request: SourceSymbolsUpdateRequest = Field(..., description="Full text symbols content to store in the program symbols resource."),
) -> SourceSymbolsUpdateResponse:
    """Update the text symbols of one ABAP program through its `/source/symbols` endpoint. The tool locks the program, writes the new symbols, and unlocks it automatically."""
    return call_program_symbols_update(systemId, name, request)


@mcp.tool()
def source_program_symbols_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program text symbols should be read."),
    name: str = Field(..., description="Technical ABAP program name whose text symbols should be read."),
    filePath: str = Field(..., description="Absolute local file path where the raw text symbols should be written."),
) -> FileTransferResponse:
    """Download the text symbols of one ABAP program to a local file from its `/source/symbols` endpoint."""
    return call_program_symbols_read_to_file(systemId, name, filePath)


@mcp.tool()
def source_program_symbols_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP program text symbols should be updated."),
    name: str = Field(..., description="Technical ABAP program name whose text symbols should be updated."),
    filePath: str = Field(..., description="Absolute local file path of the raw text symbols to upload."),
) -> FileTransferResponse:
    """Upload text symbols from a local file to one existing ABAP program through its `/source/symbols` endpoint. The tool locks the program, writes the new symbols, and unlocks it automatically."""
    return call_program_symbols_write_from_file(systemId, name, filePath)
# endregion

# region Info Repository
@mcp.tool()
def info_repository_search(systemId: str = Field(..., description="Identifier of the configured SAP system to query."),
           searchTerm: str = Field(..., description="Search pattern for the SAP repository information system. Supports wildcards such as '*' and can match object names or descriptions."),
           objectType: str = Field("", description="Optional 4-character SAP object type filter such as PROG, CLAS, FUGR, TABL, DTEL, DOMA, INTF, or DDLS.")) -> InfoRepositorySearchResponse:
    """Search the SAP repository information system of one configured SAP system for development objects."""
    return call_info_repository_search(systemId, searchTerm, objectType=objectType)
# endregion

# region Activation
@mcp.tool()
def activation_activate(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the activation should run."),
    request: ActivationActivateRequest = Field(..., description="One or more ADT object references to activate. Use ADT URIs such as /sap/bc/adt/ddic/domains/<name>, /sap/bc/adt/ddic/dataelements/<name>, /sap/bc/adt/ddic/tables/<name>, or /sap/bc/adt/ddic/db/settings/<table>.")
) -> ActivationActivateResponse:
    """Activate one or more ADT objects in one configured SAP system through the generic activation endpoint."""
    return call_activation_activate(systemId, request)
# endregion

# region CTS
@mcp.tool()
def cts_transport_check(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CTS check should run."),
    objectUri: str = Field(..., description="ADT URI of the object that may need a transport request."),
    packageName: str = Field(..., description="Package that will own or change the object."),
    operation: str = Field("I", description="CTS operation code to check, such as I for create or U for update."),
    superPackage: str = Field("", description="Optional super package name when the CTS check depends on package hierarchy."),
    recordChanges: str = Field("", description="Optional CTS record-changes flag to forward to the SAP check.")
) -> CtsTransportCheckResponse:
    """Check whether working with an object in a package requires a transport request in one configured SAP system."""
    return call_cts_transport_check(
        systemId=systemId,
        objectUri=objectUri,
        packageName=packageName,
        operation=operation,
        superPackage=superPackage,
        recordChanges=recordChanges
    )


@mcp.tool()
def cts_transport_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request should be created."),
    packageName: str = Field(..., description="Package for which the transport request will be created."),
    requestText: str = Field(..., description="Short description of the transport request."),
    objectUri: str = Field(..., description="ADT URI of the object that will be referenced by the transport request."),
    operation: str = Field("I", description="CTS operation code for the referenced change, such as I for create or U for update.")
) -> CtsTransportCreateResponse:
    """Create a transport request in one configured SAP system for a package and object reference."""
    return call_cts_transport_create(
        systemId=systemId,
        packageName=packageName,
        requestText=requestText,
        objectUri=objectUri,
        operation=operation
    )


@mcp.tool()
def cts_transport_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request should be read."),
    transportNumber: str = Field(..., description="Transport request number to read."),
) -> CtsTransportReadResponse:
    """Read a transport request in one configured SAP system through the ADT transport organizer endpoint."""
    return call_cts_transport_read(
        systemId=systemId,
        transportNumber=transportNumber,
    )


@mcp.tool()
def cts_transport_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request will be updated."),
    transportNumber: str = Field(..., description="Transport request number to update."),
    request: CtsTransportUpdateRequest = Field(..., description="Editable fields of the transport request. The tool locks the request, updates it, and unlocks it automatically."),
) -> CtsTransportUpdateResponse:
    """Update a transport request in one configured SAP system through the ADT transport organizer endpoint."""
    return call_cts_transport_update(
        systemId=systemId,
        transportNumber=transportNumber,
        request=request,
    )


@mcp.tool()
def cts_transport_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request will be deleted."),
    transportNumber: str = Field(..., description="Transport request number to delete."),
) -> CtsTransportDeleteResponse:
    """Delete a transport request in one configured SAP system through the ADT transport organizer endpoint."""
    return call_cts_transport_delete(
        systemId=systemId,
        transportNumber=transportNumber,
    )


@mcp.tool()
def cts_transport_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request should be read."),
    transportNumber: str = Field(..., description="Transport request number to download."),
    filePath: str = Field(..., description="Absolute local file path where the raw transport XML will be stored."),
) -> FileTransferResponse:
    """Download one transport request to a local file as raw ADT XML. Use this when the request contains many objects and the payload may be too large for a regular tool response."""
    return call_cts_transport_read_to_file(
        systemId=systemId,
        transportNumber=transportNumber,
        filePath=filePath,
    )


@mcp.tool()
def cts_transport_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request will be updated."),
    transportNumber: str = Field(..., description="Transport request number to update."),
    filePath: str = Field(..., description="Absolute local file path of the raw transport XML to upload."),
) -> FileTransferResponse:
    """Upload one transport request from a local file using the raw ADT XML format. The tool locks the request, writes the XML, and unlocks it automatically."""
    return call_cts_transport_write_from_file(
        systemId=systemId,
        transportNumber=transportNumber,
        filePath=filePath,
    )


@mcp.tool()
def package_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the package will be created."),
    request: PackageCreateRequest = Field(..., description="Metadata payload used to create the package."),
    corrNr: str = Field("", description="Optional transport request number passed as corrNr when creating the package.")
) -> PackageCreateResponse:
    """Create one ABAP package through the ADT packages collection endpoint."""
    return call_package_create(systemId, request, corrNr)


@mcp.tool()
def package_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the package should be read."),
    name: str = Field(..., description="Technical package name to read.")
) -> PackageReadResponse:
    """Read one ABAP package through its ADT resource URI."""
    return call_package_read(systemId, name)


@mcp.tool()
def package_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the package will be updated."),
    name: str = Field(..., description="Technical package name to update."),
    request: PackageUpdateRequest = Field(..., description="Metadata payload used to update the package.")
) -> PackageUpdateResponse:
    """Update one ABAP package through its ADT resource URI."""
    return call_package_update(systemId, name, request)


@mcp.tool()
def package_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the package will be deleted."),
    name: str = Field(..., description="Technical package name to delete.")
    ,
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete one ABAP package through the generic ADT deletion endpoint."""
    return call_package_delete(systemId, name, transportNumber)
# endregion

# region DDIC Table DB Settings
@mcp.tool()
def ddic_table_db_settings_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the table database settings should be read."),
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings should be read.")
) -> DdicTableDbSettingsReadResponse:
    """Read the database settings of a DDIC table in one configured SAP system."""
    return call_ddic_table_db_settings_read(systemId, tableName)


@mcp.tool()
def ddic_table_db_settings_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the table database settings will be updated."),
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings will be updated."),
    request: DdicTableDbSettingsUpdateRequest = Field(..., description="Set only the database settings attributes that should change. Omitted fields are kept as they are."),
    transportNumber: str = Field("", description="Transport request number to use when updating database settings in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicTableDbSettingsUpdateResponse:
    """Update the database settings of a DDIC table in one configured SAP system. The tool locks the settings object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_table_db_settings_lock(systemId, tableName)
    if not lock_response.result or not lock_response.data:
        return DdicTableDbSettingsUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock table database settings",
            "data": None
        })

    try:
        return call_ddic_table_db_settings_update(
            systemId=systemId,
            tableName=tableName,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_table_db_settings_unlock(systemId, tableName, lock_response.data.lockHandle)


@mcp.tool()
def ddic_table_db_settings_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the table database settings should be read."),
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings should be downloaded."),
    filePath: str = Field(..., description="Absolute local file path where the raw ADT XML will be stored.")
) -> FileTransferResponse:
    """Download the raw ADT XML of DDIC table database settings to a local file. The XML root is `ts:tableSettings` and commonly includes `ts:dataClassCategory`, `ts:sizeCategory`, `ts:buffering`, `ts:storageType`, and `ts:loggingEnabled`. Use this when the object content may be too large for regular tool responses."""
    try:
        content = call_ddic_table_db_settings_read_raw_content(systemId, tableName)
        size_bytes = write_text_file(filePath, content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/db/settings/{tableName.lower()}",
            mimeType="application/vnd.sap.adt.table.settings.v2+xml",
            sizeBytes=size_bytes,
            message="DDIC table database settings downloaded to local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to download DDIC table database settings to file: {str(e)}")


@mcp.tool()
def ddic_table_db_settings_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the table database settings will be updated."),
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings will be uploaded."),
    filePath: str = Field(..., description="Absolute local file path of the raw ADT XML to upload. The file must keep the same format returned by ddic_table_db_settings_read_to_file."),
    transportNumber: str = Field("", description="Transport request number to use when updating database settings in a transportable package. Leave empty for local objects such as $TMP.")
) -> FileTransferResponse:
    """Upload raw ADT XML from a local file to update DDIC table database settings. The file should preserve the `ts:tableSettings` structure returned by SAP and use the downloaded file as the template to edit. Use this when the object content may be too large for regular tool responses."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_ddic_table_db_settings_lock(systemId, tableName)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(lock_response.message or "Failed to lock table database settings", lock_response.httpCode or 500, lock_response.httpReason or "Internal Server Error")

        try:
            update_response = call_ddic_table_db_settings_update_raw(
                systemId=systemId,
                tableName=tableName,
                lockHandle=lock_response.data.lockHandle,
                rawXml=content,
                transportNumber=transportNumber
            )
        finally:
            call_ddic_table_db_settings_unlock(systemId, tableName, lock_response.data.lockHandle)

        if not update_response.result:
            return build_file_transfer_error(update_response.message or "Failed to upload DDIC table database settings from file", update_response.httpCode or 500, update_response.httpReason or "Internal Server Error")

        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/db/settings/{tableName.lower()}",
            mimeType="application/vnd.sap.adt.table.settings.v2+xml",
            sizeBytes=size_bytes,
            message="DDIC table database settings uploaded from local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to upload DDIC table database settings from file: {str(e)}")
# endregion

# region DDIC Tables
@mcp.tool()
def ddic_table_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be created."),
    name: str = Field(..., description="Technical name of the DDIC table to create."),
    description: str = Field(..., description="Short description of the DDIC table."),
    packageName: str = Field("$TMP", description="Package where the DDIC table will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC table in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC table metadata. If omitted, the configured SAP language is used.")
) -> DdicTableCreateResponse:
    """Create a DDIC table in one configured SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_table_create(
        systemId=systemId,
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_table_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table source should be read."),
    name: str = Field(..., description="Technical name of the DDIC table to read.")
) -> DdicTableReadResponse:
    """Read the current source/main content of a DDIC table in one configured SAP system."""
    return call_ddic_table_read(systemId, name)


@mcp.tool()
def ddic_table_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be updated."),
    name: str = Field(..., description="Technical name of the DDIC table to update."),
    request: DdicTableUpdateRequest = Field(..., description="Replacement source for the DDIC table. Provide the full source/main content to store."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC table in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicTableUpdateResponse:
    """Update the source/main content of a DDIC table in one configured SAP system. The tool locks the object, writes the new source, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_table_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return DdicTableUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock table",
            "data": None
        })

    try:
        return call_ddic_table_update(
            systemId=systemId,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_table_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_table_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be deleted."),
    name: str = Field(..., description="Technical name of the DDIC table to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC table from one configured SAP system through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        systemId=systemId,
        objectUri=f"/sap/bc/adt/ddic/tables/{name.lower()}",
        transportNumber=transportNumber
    )


@mcp.tool()
def ddic_table_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table source should be read."),
    name: str = Field(..., description="Technical name of the DDIC table to download."),
    filePath: str = Field(..., description="Absolute local file path where the raw `source/main` text will be stored.")
) -> FileTransferResponse:
    """Download the raw `source/main` text of a DDIC table to a local file. The file content is the exact SAP source, typically beginning with a table definition such as `define table ...`. Use this when the object content may be too large for regular tool responses."""
    try:
        content = call_ddic_table_read_raw_content(systemId, name)
        size_bytes = write_text_file(filePath, content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/tables/{name.lower()}/source/main",
            mimeType="text/plain",
            sizeBytes=size_bytes,
            message="DDIC table source downloaded to local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to download DDIC table source to file: {str(e)}")


@mcp.tool()
def ddic_table_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be updated."),
    name: str = Field(..., description="Technical name of the DDIC table to upload."),
    filePath: str = Field(..., description="Absolute local file path of the raw `source/main` text to upload. The file must keep the same format returned by ddic_table_read_to_file."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC table in a transportable package. Leave empty for local objects such as $TMP.")
) -> FileTransferResponse:
    """Upload raw `source/main` text from a local file to update a DDIC table. Use the downloaded file as the template and preserve the SAP source format. Use this when the object content may be too large for regular tool responses."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_ddic_table_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(lock_response.message or "Failed to lock table", lock_response.httpCode or 500, lock_response.httpReason or "Internal Server Error")

        try:
            update_response = call_ddic_table_update(
                systemId=systemId,
                name=name,
                lockHandle=lock_response.data.lockHandle,
                request=DdicTableUpdateRequest(source=content),
                transportNumber=transportNumber
            )
        finally:
            call_ddic_table_unlock(systemId, name, lock_response.data.lockHandle)

        if not update_response.result:
            return build_file_transfer_error(update_response.message or "Failed to upload DDIC table from file", update_response.httpCode or 500, update_response.httpReason or "Internal Server Error")

        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/tables/{name.lower()}/source/main",
            mimeType="text/plain",
            sizeBytes=size_bytes,
            message="DDIC table source uploaded from local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to upload DDIC table source from file: {str(e)}")
# endregion

# region DDIC Data Elements
@mcp.tool()
def ddic_dataelement_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be created."),
    name: str = Field(..., description="Technical name of the DDIC data element to create."),
    description: str = Field(..., description="Short description of the DDIC data element."),
    packageName: str = Field("$TMP", description="Package where the DDIC data element will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC data element in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC data element metadata. If omitted, the configured SAP language is used.")
) -> DdicDataElementCreateResponse:
    """Create a DDIC data element in one configured SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_dataelement_create(
        systemId=systemId,
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_dataelement_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element should be read."),
    name: str = Field(..., description="Technical name of the DDIC data element to read.")
) -> DdicDataElementReadResponse:
    """Read the metadata and technical settings of a DDIC data element in one configured SAP system."""
    return call_ddic_dataelement_read(systemId, name)


@mcp.tool()
def ddic_dataelement_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be updated."),
    name: str = Field(..., description="Technical name of the DDIC data element to update."),
    request: DdicDataElementUpdateRequest = Field(..., description="Set only the DDIC data element attributes that should change. Omitted fields are kept as they are."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC data element in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicDataElementUpdateResponse:
    """Update a DDIC data element in one configured SAP system. The tool locks the object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_dataelement_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return DdicDataElementUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock data element",
            "data": None
        })

    try:
        return call_ddic_dataelement_update(
            systemId=systemId,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_dataelement_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_dataelement_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be deleted."),
    name: str = Field(..., description="Technical name of the DDIC data element to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC data element from one configured SAP system through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        systemId=systemId,
        objectUri=f"/sap/bc/adt/ddic/dataelements/{name.lower()}",
        transportNumber=transportNumber
    )


@mcp.tool()
def ddic_dataelement_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element should be read."),
    name: str = Field(..., description="Technical name of the DDIC data element to download."),
    filePath: str = Field(..., description="Absolute local file path where the raw ADT XML will be stored.")
) -> FileTransferResponse:
    """Download the raw ADT XML of a DDIC data element to a local file. The XML root is `blue:wbobj` and the main payload usually lives in `dtel:dataElement`, including fields such as `dtel:typeKind`, `dtel:typeName`, `dtel:dataType`, labels, and search help properties. Use this when the object content may be too large for regular tool responses."""
    try:
        content = call_ddic_dataelement_read_raw_content(systemId, name)
        size_bytes = write_text_file(filePath, content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/dataelements/{name.lower()}",
            mimeType="application/vnd.sap.adt.dataelements.v2+xml",
            sizeBytes=size_bytes,
            message="DDIC data element downloaded to local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to download DDIC data element to file: {str(e)}")


@mcp.tool()
def ddic_dataelement_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be updated."),
    name: str = Field(..., description="Technical name of the DDIC data element to upload."),
    filePath: str = Field(..., description="Absolute local file path of the raw ADT XML to upload. The file must keep the same format returned by ddic_dataelement_read_to_file."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC data element in a transportable package. Leave empty for local objects such as $TMP.")
) -> FileTransferResponse:
    """Upload raw ADT XML from a local file to update a DDIC data element. The file should preserve the `blue:wbobj` and `dtel:dataElement` structure returned by SAP and use the downloaded file as the template to edit. Use this when the object content may be too large for regular tool responses."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_ddic_dataelement_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(lock_response.message or "Failed to lock data element", lock_response.httpCode or 500, lock_response.httpReason or "Internal Server Error")

        try:
            update_response = call_ddic_dataelement_update_raw(
                systemId=systemId,
                name=name,
                lockHandle=lock_response.data.lockHandle,
                rawXml=content,
                transportNumber=transportNumber
            )
        finally:
            call_ddic_dataelement_unlock(systemId, name, lock_response.data.lockHandle)

        if not update_response.result:
            return build_file_transfer_error(update_response.message or "Failed to upload DDIC data element from file", update_response.httpCode or 500, update_response.httpReason or "Internal Server Error")

        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/dataelements/{name.lower()}",
            mimeType="application/vnd.sap.adt.dataelements.v2+xml",
            sizeBytes=size_bytes,
            message="DDIC data element uploaded from local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to upload DDIC data element from file: {str(e)}")
# endregion

# region DDIC Domains
@mcp.tool()
def ddic_domain_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be created."),
    name: str = Field(..., description="Technical name of the DDIC domain to create."),
    description: str = Field(..., description="Short description of the DDIC domain."),
    packageName: str = Field("$TMP", description="Package where the DDIC domain will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC domain in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC domain metadata. If omitted, the configured SAP language is used.")
) -> DdicDomainCreateResponse:
    """Create a DDIC domain in one configured SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_domain_create(
        systemId=systemId,
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_domain_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain should be read."),
    name: str = Field(..., description="Technical name of the DDIC domain to read.")
) -> DdicDomainReadResponse:
    """Read the metadata and technical settings of a DDIC domain in one configured SAP system."""
    return call_ddic_domain_read(systemId, name)


@mcp.tool()
def ddic_domain_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be updated."),
    name: str = Field(..., description="Technical name of the DDIC domain to update."),
    request: DdicDomainUpdateRequest = Field(..., description="Set only the DDIC domain attributes that should change. Omitted fields are kept as they are."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC domain in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicDomainUpdateResponse:
    """Update a DDIC domain in one configured SAP system. The tool locks the object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_domain_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return DdicDomainUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock domain",
            "data": None
        })

    try:
        return call_ddic_domain_update(
            systemId=systemId,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_domain_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_domain_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be deleted."),
    name: str = Field(..., description="Technical name of the DDIC domain to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC domain from one configured SAP system through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        systemId=systemId,
        objectUri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
        transportNumber=transportNumber
    )


@mcp.tool()
def ddic_domain_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain should be read."),
    name: str = Field(..., description="Technical name of the DDIC domain to download."),
    filePath: str = Field(..., description="Absolute local file path where the raw ADT XML will be stored.")
) -> FileTransferResponse:
    """Download the raw ADT XML of a DDIC domain to a local file. The XML root is `doma:domain` and the most relevant sections usually include `doma:typeInformation`, `doma:outputInformation`, and `doma:valueInformation`. Use this when the object content may be too large for regular tool responses."""
    try:
        content = call_ddic_domain_read_raw_content(systemId, name)
        size_bytes = write_text_file(filePath, content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
            mimeType="application/vnd.sap.adt.domains.v2+xml",
            sizeBytes=size_bytes,
            message="DDIC domain downloaded to local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to download DDIC domain to file: {str(e)}")


@mcp.tool()
def ddic_domain_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be updated."),
    name: str = Field(..., description="Technical name of the DDIC domain to upload."),
    filePath: str = Field(..., description="Absolute local file path of the raw ADT XML to upload. The file must keep the same format returned by ddic_domain_read_to_file."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC domain in a transportable package. Leave empty for local objects such as $TMP.")
) -> FileTransferResponse:
    """Upload raw ADT XML from a local file to update a DDIC domain. The file should preserve the `doma:domain` structure returned by SAP and use the downloaded file as the template to edit. Use this when the object content may be too large for regular tool responses."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_ddic_domain_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(lock_response.message or "Failed to lock domain", lock_response.httpCode or 500, lock_response.httpReason or "Internal Server Error")

        try:
            update_response = call_ddic_domain_update_raw(
                systemId=systemId,
                name=name,
                lockHandle=lock_response.data.lockHandle,
                rawXml=content,
                transportNumber=transportNumber
            )
        finally:
            call_ddic_domain_unlock(systemId, name, lock_response.data.lockHandle)

        if not update_response.result:
            return build_file_transfer_error(update_response.message or "Failed to upload DDIC domain from file", update_response.httpCode or 500, update_response.httpReason or "Internal Server Error")

        return build_file_transfer_response(
            filePath=filePath,
            uri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
            mimeType="application/vnd.sap.adt.domains.v2+xml",
            sizeBytes=size_bytes,
            message="DDIC domain uploaded from local file successfully."
        )
    except ValueError as e:
        return build_file_transfer_error(str(e), 400, "Bad Request")
    except Exception as e:
        return build_file_transfer_error(f"Failed to upload DDIC domain from file: {str(e)}")
# endregion

# region DDIC DDL Sources (CDS)
@mcp.tool()
def ddic_ddl_source_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source will be created."),
    name: str = Field(..., description="Technical name of the CDS DDL source to create."),
    description: str = Field(..., description="Short description of the CDS DDL source."),
    packageName: str = Field("$TMP", description="Package where the CDS DDL source will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the CDS DDL source in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the CDS DDL source metadata. If omitted, the configured SAP language is used.")
) -> DdicDdlSourceCreateResponse:
    """Create one CDS DDL source (CDS view entity) through the ADT DDL sources collection endpoint. Returns metadata including the repository object URI and source URI."""
    return call_ddic_ddl_source_create(systemId, name, description, packageName, transportNumber, responsible, language)


@mcp.tool()
def ddic_ddl_source_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source should be read."),
    name: str = Field(..., description="Technical name of the CDS DDL source to read.")
) -> DdicDdlSourceReadResponse:
    """Read the raw source code of one CDS DDL source from its `/source/main` endpoint."""
    return call_ddic_ddl_source_read(systemId, name)


@mcp.tool()
def ddic_ddl_source_lock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source should be locked."),
    name: str = Field(..., description="Technical name of the CDS DDL source to lock.")
) -> DdicDdlSourceLockResponse:
    """Lock one CDS DDL source through the ADT lock action and return the lock handle required for source updates."""
    return call_ddic_ddl_source_lock(systemId, name)


@mcp.tool()
def ddic_ddl_source_unlock(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source should be unlocked."),
    name: str = Field(..., description="Technical name of the CDS DDL source to unlock."),
    lockHandle: str = Field(..., description="ADT lock handle previously returned by ddic_ddl_source_lock.")
) -> DdicDdlSourceLockResponse:
    """Unlock one CDS DDL source through the ADT unlock action using a previously returned lock handle."""
    return call_ddic_ddl_source_unlock(systemId, name, lockHandle)


@mcp.tool()
def ddic_ddl_source_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source should be updated."),
    name: str = Field(..., description="Technical name of the CDS DDL source to update."),
    request: DdicDdlSourceUpdateRequest = Field(..., description="Full CDS source code to store in the DDL source."),
    transportNumber: str = Field("", description="Transport request number to forward when the DDL source belongs to a transportable package.")
) -> DdicDdlSourceUpdateResponse:
    """Update the raw source code of one CDS DDL source through its `/source/main` endpoint. The tool locks the DDL source, writes the new source, and unlocks it automatically."""
    lock_response = call_ddic_ddl_source_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return DdicDdlSourceUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the DDL source.",
            "data": None
        })
    try:
        return call_ddic_ddl_source_update(systemId, name, lock_response.data.lockHandle, request, transportNumber)
    finally:
        call_ddic_ddl_source_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_ddl_source_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source will be deleted."),
    name: str = Field(..., description="Technical name of the CDS DDL source to delete."),
    transportNumber: str = Field("", description="Transport request number to use when deleting a CDS DDL source in a transportable package. Leave empty for local objects such as $TMP.")
) -> DeletionDeleteResponse:
    """Delete one CDS DDL source through the generic ADT deletion endpoint using the repository object URI."""
    return call_ddic_ddl_source_delete(systemId, name, transportNumber)


@mcp.tool()
def ddic_ddl_source_read_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source should be read."),
    name: str = Field(..., description="Technical name of the CDS DDL source to read."),
    filePath: str = Field(..., description="Absolute local file path where the CDS source will be saved.")
) -> FileTransferResponse:
    """Download the raw source code of one CDS DDL source to a local file from its `/source/main` endpoint. Use this when the object content may be too large for regular tool responses."""
    return call_ddic_ddl_source_read_to_file(systemId, name, filePath)


@mcp.tool()
def ddic_ddl_source_write_from_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CDS DDL source should be updated."),
    name: str = Field(..., description="Technical name of the CDS DDL source to update."),
    filePath: str = Field(..., description="Absolute local file path of the CDS source to upload. The file must keep the same format returned by ddic_ddl_source_read_to_file."),
    transportNumber: str = Field("", description="Transport request number to forward when the DDL source belongs to a transportable package. Leave empty for local objects such as $TMP.")
) -> FileTransferResponse:
    """Upload raw CDS source code from a local file to one existing CDS DDL source through its `/source/main` endpoint. The tool locks the DDL source, writes the new source, and unlocks it automatically."""
    return call_ddic_ddl_source_write_from_file(systemId, name, filePath, transportNumber)
# endregion

def _parse_args() -> argparse.Namespace:
    """Parse the local command-line options used to launch the server."""
    parser = argparse.ArgumentParser(description="ABAP FastMCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--path", default="/mcp/abap")
    parser.add_argument("--log-level", default="info")
    return parser.parse_args()


if __name__ == "__main__":
    print("\n--- Initiating FastMCP server through __main__ ---")
    args = _parse_args()
    RUN_HOST = args.host
    RUN_PORT = args.port
    RUN_PATH = args.path
    RUN_TRANSPORT = args.transport
    if args.transport == "stdio":
        mcp.run(transport="stdio", log_level=args.log_level, show_banner=False)
    else:
        _configure_startup_logging()
        configure_dashboard_mcp_target(args.host, args.port, args.path)
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            path=args.path,
            log_level=args.log_level,
            show_banner=False,
        )
