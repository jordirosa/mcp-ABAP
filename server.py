import argparse
import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Callable, Literal
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
from datapreview.datapreview import *
from deletion.deletion import *
from docu.abap.docu_abap import *
from ddic.db.settings import *
from ddic.dataelements.dataelements import *
from ddic.ddl.ddl import *
from ddic.domains.domains import *
from ddic.tables.tables import *
from generics import FileTransferOutput, FileTransferResponse
from gui.gui import *
from info_repository.info_repository import *
from knowledge.knowledge import *
from navigation.navigation import *
from packages.packages import *
from internals.internals import *
from internals.workflows.engine import (
    workflow_cancel as call_workflow_cancel,
    workflow_continue as call_workflow_continue,
    workflow_log as call_workflow_log,
    workflow_start as call_workflow_start,
    workflow_status as call_workflow_status,
)
from internals.workflows.models import WorkflowLogResponse, WorkflowResponse
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
from abapunit.abapunit import *
from classrun.classrun import *
from checkruns.checkruns import *
from codecompletion.codecompletion import *
from webgui.webgui import *

LOGGER = logging.getLogger("abap_mcp")
HTTP_DASHBOARD_CONFIG_PATH = "/mcp/abap/api/dashboard/config"
HTTP_DASHBOARD_SAPLOGON_PATH = "/mcp/abap/api/dashboard/saplogon"
HTTP_DASHBOARD_PLAYWRIGHT_STATUS_PATH = "/mcp/abap/api/dashboard/playwright/status"
HTTP_DASHBOARD_PLAYWRIGHT_INSTALL_PATH = "/mcp/abap/api/dashboard/playwright/install"
HTTP_DASHBOARD_MCP_STATUS_PATH = "/mcp/abap/api/dashboard/mcp-status"
HTTP_DASHBOARD_MEMORY_TREE_PATH = "/mcp/abap/api/dashboard/memory/tree"
HTTP_DASHBOARD_MEMORY_DOCUMENT_PATH = "/mcp/abap/api/dashboard/memory/document"
HTTP_DASHBOARD_PATH = "/mcp/abap/dashboard"
RUN_TRANSPORT = "stdio"
RUN_HOST = "127.0.0.1"
RUN_PORT = 8081
RUN_PATH = "/mcp/abap"
TOOL_MODE_ENV_VAR = "ABAP_MCP_TOOL_MODE"
TOOL_MODE_FULL = "full"
TOOL_MODE_COMPACT = "compact"
COMPACT_TOOL_NAMES = {
    "abap_list_capabilities",
    "abap_get_capability_spec",
    "abap_call_capability",
    "abap_skills_install",
}
COMPACT_DISPATCHER_TOOL_NAMES = {
    "abap_list_capabilities",
    "abap_get_capability_spec",
    "abap_call_capability",
}
CAPABILITY_TOOLS: dict[str, Any] = {}


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


def _build_startup_urls(host: str, port: int, path: str) -> dict[str, str]:
    """Build the URLs shown once the HTTP dashboard is reachable."""
    normalized_path = str(path or RUN_PATH).strip() or RUN_PATH
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    base = f"http://{host}:{int(port)}"
    return {
        "mcp": f"{base}{normalized_path.rstrip('/')}",
        "dashboard": f"{base}{HTTP_DASHBOARD_PATH}",
    }


def _read_http_status(url: str, timeout_seconds: float) -> int:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return int(response.status)


async def _wait_for_dashboard_http_200(
    dashboard_url: str,
    timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 0.25,
    status_reader: Callable[[str, float], int] | None = None,
) -> bool:
    """Wait until the dashboard route responds with HTTP 200."""
    reader = status_reader or _read_http_status
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        try:
            status = await asyncio.to_thread(reader, dashboard_url, min(2.0, retry_interval_seconds))
            if status == 200:
                return True
        except (OSError, urllib.error.URLError, TimeoutError):
            pass
        await asyncio.sleep(retry_interval_seconds)
    return False


async def _log_startup_urls_when_dashboard_ready(startup_started: float) -> None:
    urls = _build_startup_urls(RUN_HOST, RUN_PORT, RUN_PATH)
    if await _wait_for_dashboard_http_200(urls["dashboard"]):
        elapsed = time.perf_counter() - startup_started
        LOGGER.info("ABAP MCP server is ready (%.2fs)", elapsed)
        LOGGER.info("MCP endpoint: %s", urls["mcp"])
        LOGGER.info("Dashboard: %s", urls["dashboard"])
        return
    LOGGER.warning(
        "ABAP MCP server started, but dashboard readiness could not be confirmed within 30 seconds: %s",
        urls["dashboard"],
    )


@asynccontextmanager
async def abap_lifespan(_server: FastMCP):
    """Warm heavy runtime pieces only when running the MCP over HTTP."""
    if RUN_TRANSPORT == "stdio":
        yield
        return

    _configure_startup_logging()
    startup_started = time.perf_counter()
    LOGGER.info("Starting ABAP MCP server...")
    knowledge_started = time.perf_counter()
    try:
        knowledge_info = warm_knowledge_runtime()
        LOGGER.info(
            "Knowledge runtime ready. collection=%s chroma=%s documents=%s model=%s (%.2fs)",
            knowledge_info.collectionName,
            knowledge_info.chromaPath,
            knowledge_info.documentsPath,
            knowledge_info.embeddingModel,
            time.perf_counter() - knowledge_started,
        )
    except Exception as exc:
        LOGGER.warning(
            "Knowledge runtime could not be warmed up and will initialize on demand: %s (%.2fs)",
            str(exc),
            time.perf_counter() - knowledge_started,
        )
    readiness_task = asyncio.create_task(_log_startup_urls_when_dashboard_ready(startup_started))
    try:
        yield
    finally:
        if not readiness_task.done():
            readiness_task.cancel()
        LOGGER.info("Shutting down ABAP MCP server...")


def _get_playwright_status() -> dict:
    """Check whether the Playwright Python package and the Chromium browser are installed."""
    import importlib.util
    import os

    package_installed = importlib.util.find_spec("playwright") is not None
    package_version = ""
    if package_installed:
        try:
            from importlib.metadata import version as _pkg_version
            package_version = _pkg_version("playwright")
        except Exception:
            pass

    browser_installed = False
    if package_installed:
        try:
            from playwright.sync_api import sync_playwright as _swp
            _instance = _swp().start()
            browser_installed = os.path.exists(_instance.chromium.executable_path)
            _instance.stop()
        except Exception:
            browser_installed = False

    return {
        "packageInstalled": package_installed,
        "packageVersion": package_version,
        "browserInstalled": browser_installed,
    }


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
    .wrap {{ width: 100%; margin: 0; padding: 32px 20px 48px; }}
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
    .save-dot {{
      display: inline-block;
      vertical-align: -1px;
      margin-right: 10px;
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
    .toast-region {{
      position: fixed;
      top: 18px;
      right: 18px;
      z-index: 2000;
      display: flex;
      flex-direction: column;
      gap: 10px;
      width: min(420px, calc(100vw - 36px));
      pointer-events: none;
    }}
    .toast {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: start;
      padding: 13px 14px;
      border: 1px solid var(--line-strong);
      border-radius: 14px;
      background: rgba(17, 25, 35, 0.98);
      color: var(--ink);
      box-shadow: 0 18px 44px var(--shadow);
      pointer-events: auto;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .toast.info {{ border-color: rgba(100, 210, 255, 0.45); }}
    .toast.success {{ border-color: rgba(101, 214, 166, 0.55); }}
    .toast.warning {{ border-color: rgba(245, 199, 106, 0.58); }}
    .toast.error {{ border-color: rgba(255, 107, 122, 0.62); }}
    .toast-message {{
      font-weight: 650;
      line-height: 1.42;
    }}
    .toast-close {{
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.04);
      color: var(--ink);
      border-radius: 999px;
      width: 26px;
      height: 26px;
      cursor: pointer;
      font-weight: 800;
      line-height: 1;
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
    .language-control {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 220px;
    }}
    .language-control label {{
      margin: 0;
      color: var(--muted);
      white-space: nowrap;
    }}
    .language-control select {{
      width: auto;
      min-width: 132px;
      padding: 8px 10px;
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
          <p style="margin:8px 0 0;" data-i18n="hero.subtitle">Gestiona las conexiones SAP configuradas en el archivo <code>.env</code> sin editarlo a mano.</p>
        </div>
        <div class="language-control">
          <label for="languageSelect" data-i18n="language.label">Idioma</label>
          <select id="languageSelect" aria-label="Idioma">
            <option value="es">Español</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>
    </div>

    <div class="panel" style="padding:14px 18px;">
      <div class="tabbar" role="tablist" aria-label="Secciones del dashboard" data-i18n-aria-label="tabs.aria">
        <button class="tab-button active" id="tabButtonMcp" data-tab="mcp" type="button" role="tab" aria-selected="true">MCP</button>
        <button class="tab-button" id="tabButtonEnv" data-tab="env" type="button" role="tab" aria-selected="false">.env</button>
        <button class="tab-button" id="tabButtonMemory" data-tab="memory" type="button" role="tab" aria-selected="false">Memory</button>
      </div>
    </div>

    <section id="tabPanelMcp" class="tab-panel">
      <div class="panel">
        <div class="toolbar">
          <div>
            <strong data-i18n="mcp.title">Clientes MCP</strong>
            <p style="margin:8px 0 0;" data-i18n="mcp.description">Comprueba si el servidor ABAP MCP está registrado en cada cliente local.</p>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>CLI</th>
                <th data-i18n="mcp.client">Cliente</th>
                <th data-i18n="mcp.file">Fichero</th>
                <th>MCP</th>
                <th data-i18n="common.actions">Acciones</th>
                <th>Info</th>
              </tr>
            </thead>
            <tbody id="mcpClientsTableBody"></tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <div class="toolbar">
          <div>
            <strong>Playwright</strong>
            <p style="margin:8px 0 0;" data-i18n="playwright.description">Requerido para las tools de SAP WebGUI. Necesita el paquete Python y el navegador Chromium.</p>
          </div>
          <button class="button secondary" id="refreshPlaywrightButton" type="button" data-i18n="common.refresh">Actualizar</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th data-i18n="playwright.component">Componente</th>
                <th data-i18n="playwright.status">Estado</th>
                <th data-i18n="common.action">Acción</th>
              </tr>
            </thead>
            <tbody id="playwrightTableBody"></tbody>
          </table>
        </div>
        <div id="playwrightLog" style="display:none; margin-top:12px; padding:10px 12px; background:var(--bg); border:1px solid var(--border); border-radius:6px; font-family:monospace; font-size:12px; white-space:pre-wrap; max-height:180px; overflow-y:auto;"></div>
      </div>
    </section>

    <section id="tabPanelEnv" class="tab-panel" hidden>
      <div class="panel">
        <div class="field">
          <label for="sapGuiExecutablePath" data-i18n="env.saplogonPath">Ruta de <code>saplogon.exe</code></label>
          <input id="sapGuiExecutablePath" type="text" placeholder="Opcional. Si está vacío, el servidor intentará encontrar SAP GUI por PATH o rutas habituales." data-i18n-placeholder="env.saplogonPlaceholder" />
        </div>
      </div>

      <div class="panel">
        <div class="toolbar">
          <strong data-i18n="env.connections">Conexiones SAP</strong>
          <div class="inline-actions">
            <button class="button" id="saveButton" type="button"><span class="signal-dot ok save-dot" id="saveDirtyDot"></span><span data-i18n="common.saveChanges">Guardar cambios</span></button>
            <button class="button secondary" id="addSystemButton" type="button" data-i18n="env.addConnection">Añadir conexión</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th data-i18n="field.name">Nombre</th>
                <th data-i18n="field.type">Tipo</th>
                <th data-i18n="field.server">Servidor</th>
                <th data-i18n="field.client">Cliente</th>
                <th data-i18n="field.language">Idioma</th>
                <th>SSL</th>
                <th data-i18n="field.sapGuiEntry">Entrada SAP GUI</th>
                <th>URL WebGUI</th>
                <th data-i18n="common.actions">Acciones</th>
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
            <p style="margin:8px 0 0;" data-i18n="memory.description">Explora los documentos locales de conocimiento almacenados en <code>db/documents</code>.</p>
          </div>
        </div>
        <div class="memory-layout">
          <div class="memory-pane">
            <div class="memory-filter">
              <input id="memoryFilter" type="text" placeholder="Filtrar documentos y carpetas..." data-i18n-placeholder="memory.filterPlaceholder" />
            </div>
            <div class="tree-scroll memory-tree" id="memoryTree"></div>
          </div>
          <div class="memory-pane">
            <div class="viewer-toolbar">
              <strong id="memoryViewerTitle" data-i18n="memory.document">Documento</strong>
              <span class="subtle" id="memoryViewerMeta" data-i18n="memory.selectFile">Selecciona un fichero .md o .pdf</span>
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
        <button class="button secondary" type="button" id="closeDialogButton" data-i18n="common.close">Cerrar</button>
      </div>
      <div class="grid">
        <div class="field">
          <label for="systemId">ID</label>
          <input id="systemId" type="text" maxlength="30" required />
        </div>
        <div class="field">
          <label for="systemName" data-i18n="field.name">Nombre</label>
          <input id="systemName" type="text" required />
        </div>
        <div class="field">
          <label for="systemType" data-i18n="field.type">Tipo</label>
          <input id="systemType" type="text" required />
        </div>
        <div class="field">
          <label for="systemServer" data-i18n="field.server">Servidor</label>
          <input id="systemServer" type="text" required />
        </div>
        <div class="field">
          <label for="systemUser" data-i18n="field.user">Usuario</label>
          <input id="systemUser" type="text" required />
        </div>
        <div class="field">
          <label for="systemPassword">Password</label>
          <input id="systemPassword" type="password" required />
        </div>
        <div class="field">
          <label for="systemClient" data-i18n="field.client">Cliente</label>
          <input id="systemClient" type="text" required />
        </div>
        <div class="field">
          <label for="systemLanguage" data-i18n="field.language">Idioma</label>
          <input id="systemLanguage" type="text" value="EN" />
        </div>
        <div class="field full">
          <label for="sapGuiConnectionName" data-i18n="field.sapGuiEntry">Entrada de SAP GUI</label>
          <input id="sapGuiConnectionName" type="text" placeholder="Nombre exacto en SAP Logon" data-i18n-placeholder="field.sapGuiEntryPlaceholder" />
        </div>
        <div class="field full">
          <label for="sapWebguiUrl">URL WebGUI</label>
          <input id="sapWebguiUrl" type="text" placeholder="https://servidor:puerto/sap/bc/gui/sap/its/webgui" data-i18n-placeholder="field.webguiPlaceholder" />
        </div>
        <div class="field full">
          <div class="inline-actions">
            <button class="button secondary" type="button" id="importSapLogonButton" data-i18n="saplogon.import">Importar desde SAP Logon</button>
            <button class="button secondary" type="button" id="openPortHelpButton" title="Abrir ayuda para localizar el puerto HTTPS en SAP GUI" data-i18n-title="saplogon.helpTitle">?</button>
          </div>
        </div>
        <div class="field full checkbox-row">
          <input id="verifySsl" type="checkbox" />
          <label for="verifySsl" style="margin:0;" data-i18n="field.verifySsl">Verificar certificados SSL</label>
        </div>
      </div>
      <div class="toolbar" style="margin-top:18px;">
        <div></div>
        <button class="button" type="submit" data-i18n="env.saveConnection">Guardar conexión</button>
      </div>
    </form>
  </dialog>

  <dialog id="sapLogonDialog">
    <div class="modal">
      <div class="toolbar">
        <strong data-i18n="saplogon.entries">Entradas de SAP Logon</strong>
        <button class="button secondary" type="button" id="closeSapLogonDialogButton" data-i18n="common.close">Cerrar</button>
      </div>
      <p style="margin:0 0 14px; color: var(--muted);" data-i18n="saplogon.description">Selecciona una entrada. El dashboard rellenará el nombre de conexión y, si lo has indicado, intentará abrir SAP GUI para localizar automáticamente el puerto HTTPS en <code>SMICM</code>.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th data-i18n="field.name">Nombre</th>
              <th>ID sistema</th>
              <th>Host</th>
              <th data-i18n="field.port">Puerto</th>
              <th data-i18n="common.action">Acción</th>
            </tr>
          </thead>
          <tbody id="sapLogonTableBody"></tbody>
        </table>
      </div>
    </div>
  </dialog>
  <div class="toast-region" id="toastRegion" aria-live="polite" aria-atomic="true"></div>

  <script>
    const configUrl = {json.dumps(config_url)};
    const sapLogonUrl = {json.dumps(HTTP_DASHBOARD_SAPLOGON_PATH)};
    const sapLogonImportUrl = {json.dumps(HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH)};
    const mcpStatusUrl = {json.dumps(HTTP_DASHBOARD_MCP_STATUS_PATH)};
    const mcpActionUrl = {json.dumps(HTTP_DASHBOARD_MCP_ACTION_PATH)};
    const portHelpUrl = {json.dumps(HTTP_DASHBOARD_PORT_HELP_PATH)};
    const memoryTreeUrl = {json.dumps(HTTP_DASHBOARD_MEMORY_TREE_PATH)};
    const memoryDocumentUrl = {json.dumps(HTTP_DASHBOARD_MEMORY_DOCUMENT_PATH)};
    const playwrightStatusUrl = {json.dumps(HTTP_DASHBOARD_PLAYWRIGHT_STATUS_PATH)};
    const playwrightInstallUrl = {json.dumps(HTTP_DASHBOARD_PLAYWRIGHT_INSTALL_PATH)};
    const languageStorageKey = "abapMcpDashboardLanguage";
    const supportedLanguages = ["es", "en"];
    const translations = {{
      es: {{
        "hero.subtitle": 'Gestiona las conexiones SAP configuradas en el archivo <code>.env</code> sin editarlo a mano.',
        "language.label": "Idioma",
        "tabs.aria": "Secciones del dashboard",
        "mcp.title": "Clientes MCP",
        "mcp.description": "Comprueba si el servidor ABAP MCP está registrado en cada cliente local.",
        "mcp.client": "Cliente",
        "mcp.file": "Fichero",
        "common.actions": "Acciones",
        "common.action": "Acción",
        "common.refresh": "Actualizar",
        "common.close": "Cerrar",
        "common.saveChanges": "Guardar cambios",
        "common.yes": "Sí",
        "common.no": "No",
        "common.edit": "Editar",
        "common.delete": "Eliminar",
        "common.insert": "Insertar",
        "common.adjust": "Ajustar",
        "common.use": "Usar",
        "common.installed": "Instalado",
        "common.notDetected": "No detectado",
        "playwright.description": "Requerido para las tools de SAP WebGUI. Necesita el paquete Python y el navegador Chromium.",
        "playwright.component": "Componente",
        "playwright.status": "Estado",
        "playwright.chromium": "Navegador Chromium",
        "playwright.notInstalled": "No instalado",
        "playwright.checking": "Comprobando...",
        "playwright.packageMissing": "El paquete playwright no está instalado. Ejecuta: pip install playwright",
        "playwright.running": "Ejecutando: {{label}}\\nEspera, esto puede tardar unos minutos...",
        "playwright.runningToast": "Ejecutando {{label}}...",
        "playwright.noOutput": "Sin salida.",
        "playwright.failed": "La instalación de Playwright no se completó correctamente.",
        "playwright.completed": "Completado.",
        "playwright.completedToast": "Instalación de Playwright completada.",
        "playwright.errorCheck": "Error al comprobar Playwright.",
        "playwright.errorRun": "Error al ejecutar la instalación de Playwright.",
        "env.saplogonPath": 'Ruta de <code>saplogon.exe</code>',
        "env.saplogonPlaceholder": "Opcional. Si está vacío, el servidor intentará encontrar SAP GUI por PATH o rutas habituales.",
        "env.connections": "Conexiones SAP",
        "env.addConnection": "Añadir conexión",
        "env.saveConnection": "Guardar conexión",
        "env.noSystems": "No hay conexiones configuradas.",
        "env.connectionDeleted": "Conexión eliminada de la lista. Falta guardar para persistir el cambio.",
        "env.connectionReady": "Conexión preparada. Falta guardar para persistir el cambio.",
        "env.saveDirty": "Hay cambios pendientes de guardar.",
        "env.saveClean": "No hay cambios pendientes.",
        "env.addDialog": "Añadir conexión SAP",
        "env.editDialog": "Editar conexión SAP",
        "field.name": "Nombre",
        "field.type": "Tipo",
        "field.server": "Servidor",
        "field.client": "Cliente",
        "field.language": "Idioma",
        "field.user": "Usuario",
        "field.sapGuiEntry": "Entrada de SAP GUI",
        "field.sapGuiEntryPlaceholder": "Nombre exacto en SAP Logon",
        "field.webguiPlaceholder": "https://servidor:puerto/sap/bc/gui/sap/its/webgui",
        "field.verifySsl": "Verificar certificados SSL",
        "field.port": "Puerto",
        "memory.description": 'Explora los documentos locales de conocimiento almacenados en <code>db/documents</code>.',
        "memory.filterPlaceholder": "Filtrar documentos y carpetas...",
        "memory.document": "Documento",
        "memory.selectFile": "Selecciona un fichero .md o .pdf",
        "memory.placeholder": "Selecciona un documento del árbol para verlo aquí.",
        "memory.noMatches": "No hay documentos .md o .pdf que coincidan con el filtro.",
        "memory.folderFallback": "(carpeta)",
        "memory.fileFallback": "(fichero)",
        "memory.loadTreeError": "No se pudo cargar el árbol de memoria.",
        "memory.openError": "No se pudo abrir el documento de memoria.",
        "saplogon.import": "Importar desde SAP Logon",
        "saplogon.helpTitle": "Abrir ayuda para localizar el puerto HTTPS en SAP GUI",
        "saplogon.entries": "Entradas de SAP Logon",
        "saplogon.description": "Selecciona una entrada. El dashboard rellenará el nombre de conexión y, si lo has indicado, intentará abrir SAP GUI para localizar automáticamente el puerto HTTPS en SMICM.",
        "saplogon.noEntries": "No se han encontrado entradas de SAP Logon.",
        "saplogon.loadError": "No se pudieron cargar las entradas de SAP Logon.",
        "saplogon.basicApplied": "Importación básica aplicada desde SAP Logon. La búsqueda automática del puerto se ha omitido.",
        "saplogon.searchingPort": "Buscando el puerto HTTPS en SAP GUI...",
        "saplogon.autoImportSuccess": "Importación completada con autodetección del puerto HTTPS.",
        "saplogon.autoImportError": "No se pudo descubrir el puerto HTTPS automáticamente. Usa la ayuda manual.",
        "saplogon.confirmAutomation": "¿Quieres lanzar la automatización que intenta encontrar el puerto HTTPS de tu sistema SAP?",
        "saplogon.credentialsRequired": "Rellena usuario y password en la conexión y vuelve a lanzar la importación desde SAP Logon.",
        "config.loading": "Cargando configuración...",
        "config.loaded": "Configuración cargada.",
        "config.loadError": "No se pudo cargar la configuración.",
        "config.saving": "Guardando configuración...",
        "config.saved": "Configuración guardada.",
        "config.saveError": "No se pudo guardar la configuración.",
        "mcp.noData": "No hay datos de clientes MCP.",
        "mcp.loadError": "No se pudo cargar el estado MCP.",
        "mcp.actionApplied": "Acción MCP aplicada.",
        "mcp.actionError": "No se pudo aplicar la acción MCP.",
        "toast.close": "Cerrar mensaje",
      }},
      en: {{
        "hero.subtitle": 'Manage SAP connections configured in the <code>.env</code> file without editing it by hand.',
        "language.label": "Language",
        "tabs.aria": "Dashboard sections",
        "mcp.title": "MCP clients",
        "mcp.description": "Check whether the ABAP MCP server is registered in each local client.",
        "mcp.client": "Client",
        "mcp.file": "File",
        "common.actions": "Actions",
        "common.action": "Action",
        "common.refresh": "Refresh",
        "common.close": "Close",
        "common.saveChanges": "Save changes",
        "common.yes": "Yes",
        "common.no": "No",
        "common.edit": "Edit",
        "common.delete": "Delete",
        "common.insert": "Insert",
        "common.adjust": "Adjust",
        "common.use": "Use",
        "common.installed": "Installed",
        "common.notDetected": "Not detected",
        "playwright.description": "Required by the SAP WebGUI tools. Needs the Python package and the Chromium browser.",
        "playwright.component": "Component",
        "playwright.status": "Status",
        "playwright.chromium": "Chromium browser",
        "playwright.notInstalled": "Not installed",
        "playwright.checking": "Checking...",
        "playwright.packageMissing": "The playwright package is not installed. Run: pip install playwright",
        "playwright.running": "Running: {{label}}\\nPlease wait, this may take a few minutes...",
        "playwright.runningToast": "Running {{label}}...",
        "playwright.noOutput": "No output.",
        "playwright.failed": "The Playwright installation did not complete successfully.",
        "playwright.completed": "Completed.",
        "playwright.completedToast": "Playwright installation completed.",
        "playwright.errorCheck": "Failed to check Playwright.",
        "playwright.errorRun": "Failed to run the Playwright installation.",
        "env.saplogonPath": '<code>saplogon.exe</code> path',
        "env.saplogonPlaceholder": "Optional. If empty, the server will try PATH and common locations.",
        "env.connections": "SAP connections",
        "env.addConnection": "Add connection",
        "env.saveConnection": "Save connection",
        "env.noSystems": "No connections configured.",
        "env.connectionDeleted": "Connection removed from the list. Save changes to persist it.",
        "env.connectionReady": "Connection prepared. Save changes to persist it.",
        "env.saveDirty": "There are unsaved changes.",
        "env.saveClean": "No unsaved changes.",
        "env.addDialog": "Add SAP connection",
        "env.editDialog": "Edit SAP connection",
        "field.name": "Name",
        "field.type": "Type",
        "field.server": "Server",
        "field.client": "Client",
        "field.language": "Language",
        "field.user": "User",
        "field.sapGuiEntry": "SAP GUI entry",
        "field.sapGuiEntryPlaceholder": "Exact name in SAP Logon",
        "field.webguiPlaceholder": "https://server:port/sap/bc/gui/sap/its/webgui",
        "field.verifySsl": "Verify SSL certificates",
        "field.port": "Port",
        "memory.description": 'Browse local knowledge documents stored in <code>db/documents</code>.',
        "memory.filterPlaceholder": "Filter documents and folders...",
        "memory.document": "Document",
        "memory.selectFile": "Select an .md or .pdf file",
        "memory.placeholder": "Select a document from the tree to view it here.",
        "memory.noMatches": "No .md or .pdf documents match the filter.",
        "memory.folderFallback": "(folder)",
        "memory.fileFallback": "(file)",
        "memory.loadTreeError": "Failed to load the memory tree.",
        "memory.openError": "Failed to open the memory document.",
        "saplogon.import": "Import from SAP Logon",
        "saplogon.helpTitle": "Open help for locating the HTTPS port in SAP GUI",
        "saplogon.entries": "SAP Logon entries",
        "saplogon.description": "Select an entry. The dashboard will fill the connection name and, if requested, try to open SAP GUI to automatically locate the HTTPS port in SMICM.",
        "saplogon.noEntries": "No SAP Logon entries were found.",
        "saplogon.loadError": "Failed to load SAP Logon entries.",
        "saplogon.basicApplied": "Basic import applied from SAP Logon. Automatic port discovery was skipped.",
        "saplogon.searchingPort": "Searching for the HTTPS port in SAP GUI...",
        "saplogon.autoImportSuccess": "Import completed with automatic HTTPS port detection.",
        "saplogon.autoImportError": "Could not discover the HTTPS port automatically. Use the manual help.",
        "saplogon.confirmAutomation": "Do you want to run the automation that tries to find the HTTPS port of your SAP system?",
        "saplogon.credentialsRequired": "Fill in user and password in the connection, then run the SAP Logon import again.",
        "config.loading": "Loading configuration...",
        "config.loaded": "Configuration loaded.",
        "config.loadError": "Failed to load configuration.",
        "config.saving": "Saving configuration...",
        "config.saved": "Configuration saved.",
        "config.saveError": "Failed to save configuration.",
        "mcp.noData": "No MCP client data.",
        "mcp.loadError": "Failed to load MCP status.",
        "mcp.actionApplied": "MCP action applied.",
        "mcp.actionError": "Failed to apply the MCP action.",
        "toast.close": "Close message",
      }},
    }};
    const systems = [];
    const mcpClients = [];
    let sapLogonEntries = [];
    let memoryNodes = [];
    let selectedMemoryPath = "";
    let sapLogonImportMode = "auto";
    let editingIndex = null;
    let activeTab = "mcp";
    let savedEnvSnapshot = "";
    let lastPlaywrightStatus = null;
    let currentLanguage = supportedLanguages.includes(localStorage.getItem(languageStorageKey))
      ? localStorage.getItem(languageStorageKey)
      : "es";

    const toastRegion = document.getElementById("toastRegion");
    const languageSelect = document.getElementById("languageSelect");
    const tableBody = document.getElementById("systemsTableBody");
    const mcpClientsTableBody = document.getElementById("mcpClientsTableBody");
    const sapGuiExecutablePathInput = document.getElementById("sapGuiExecutablePath");
    const saveDirtyDot = document.getElementById("saveDirtyDot");
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

    function t(key, params = {{}}) {{
      let text = (translations[currentLanguage] && translations[currentLanguage][key])
        || (translations.es && translations.es[key])
        || key;
      Object.entries(params).forEach(([name, value]) => {{
        text = text.replaceAll("{{{{" + name + "}}}}", String(value));
        text = text.replaceAll("{{" + name + "}}", String(value));
      }});
      return text;
    }}

    function apiUrl(url) {{
      const separator = url.includes("?") ? "&" : "?";
      return `${{url}}${{separator}}lang=${{encodeURIComponent(currentLanguage)}}`;
    }}

    function applyTranslations() {{
      document.documentElement.lang = currentLanguage;
      languageSelect.value = currentLanguage;
      document.querySelectorAll("[data-i18n]").forEach((node) => {{
        node.innerHTML = t(node.dataset.i18n);
      }});
      document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {{
        node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
      }});
      document.querySelectorAll("[data-i18n-title]").forEach((node) => {{
        node.setAttribute("title", t(node.dataset.i18nTitle));
      }});
      document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {{
        node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
      }});
      renderSystems();
      renderMcpClients();
      if (lastPlaywrightStatus) {{
        renderPlaywrightStatus(lastPlaywrightStatus);
      }}
      renderMemoryTree();
      renderSapLogonEntries();
      if (!selectedMemoryPath) {{
        showMemoryPlaceholder();
      }}
      if (editorDialog.open) {{
        dialogTitle.textContent = editingIndex === null ? t("env.addDialog") : t("env.editDialog");
      }}
      updateSaveDirtyState();
    }}

    function setLanguage(language) {{
      currentLanguage = supportedLanguages.includes(language) ? language : "es";
      localStorage.setItem(languageStorageKey, currentLanguage);
      applyTranslations();
      loadMcpClients().catch((error) => {{
        console.error(error);
        showToast(error.message || t("mcp.loadError"), "error");
      }});
    }}

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
        row.innerHTML = `<td colspan="10" style="color:#66604f;">${{escapeHtml(t("env.noSystems"))}}</td>`;
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
          <td>${{system.verify_ssl ? t("common.yes") : t("common.no")}}</td>
          <td>${{escapeHtml(system.sap_gui_connection_name || "")}}</td>
          <td>${{escapeHtml(system.sap_webgui_url || "")}}</td>
          <td>
            <div class="inline-actions">
              <button class="button secondary" type="button" data-action="edit" data-index="${{index}}">${{t("common.edit")}}</button>
              <button class="button danger" type="button" data-action="delete" data-index="${{index}}">${{t("common.delete")}}</button>
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
        row.innerHTML = `<td colspan="6" class="subtle">${{escapeHtml(t("mcp.noData"))}}</td>`;
        mcpClientsTableBody.appendChild(row);
        return;
      }}

      mcpClients.forEach((client) => {{
        const row = document.createElement("tr");
        const cliClass = client.cliInstalled ? "ok" : "off";
        const mcpClass = client.mcpState === "match" ? "ok" : (client.mcpState === "mismatch" ? "warn" : "off");
        const actions = (client.actions || []).map((action) => {{
          const label = action === "insert" ? t("common.insert") : (action === "adjust" ? t("common.adjust") : t("common.delete"));
          const buttonClass = action === "delete" ? "danger" : (action === "adjust" ? "warning" : "secondary");
          return `<button class="button ${{buttonClass}}" type="button" data-mcp-action="${{action}}" data-client-id="${{client.id}}">${{label}}</button>`;
        }}).join("");
        row.innerHTML = `
          <td><span class="signal" title="${{escapeHtml(client.cliDetail || "")}}"><span class="signal-dot ${{cliClass}}"></span>${{client.cliInstalled ? t("common.installed") : t("common.notDetected")}}</span></td>
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

    function showToast(message, type = "info", options = {{}}) {{
      placeToastRegion();
      const normalizedType = ["info", "success", "warning", "error"].includes(type) ? type : "info";
      const toast = document.createElement("div");
      toast.className = `toast ${{normalizedType}}`;
      toast.setAttribute("role", normalizedType === "error" ? "alert" : "status");
      const messageEl = document.createElement("div");
      messageEl.className = "toast-message";
      messageEl.textContent = message || "";
      const closeButton = document.createElement("button");
      closeButton.className = "toast-close";
      closeButton.type = "button";
      closeButton.setAttribute("aria-label", t("toast.close"));
      closeButton.textContent = "x";
      toast.appendChild(messageEl);
      toast.appendChild(closeButton);
      toastRegion.prepend(toast);

      while (toastRegion.children.length > 4) {{
        toastRegion.lastElementChild.remove();
      }}

      const removeToast = () => {{
        if (toast.isConnected) {{
          toast.remove();
        }}
      }};
      closeButton.addEventListener("click", removeToast);
      const duration = Number(options.durationMs || (normalizedType === "error" ? 8000 : 5000));
      if (duration > 0) {{
        window.setTimeout(removeToast, duration);
      }}
    }}

    function placeToastRegion() {{
      const openDialogs = Array.from(document.querySelectorAll("dialog[open]"));
      const host = openDialogs.length ? openDialogs[openDialogs.length - 1] : document.body;
      if (toastRegion.parentElement !== host) {{
        host.appendChild(toastRegion);
      }}
    }}

    function normalizedEnvState() {{
      return JSON.stringify({{
        sapGuiExecutablePath: sapGuiExecutablePathInput.value.trim(),
        systems: systems.map((system) => ({{
          id: system.id || "",
          name: system.name || "",
          type: system.type || "",
          server: system.server || "",
          user: system.user || "",
          password: system.password || "",
          client: system.client || "",
          language: system.language || "",
          verify_ssl: Boolean(system.verify_ssl),
          sap_gui_connection_name: system.sap_gui_connection_name || "",
          sap_webgui_url: system.sap_webgui_url || "",
        }})),
      }});
    }}

    function updateSaveDirtyState() {{
      const hasChanges = normalizedEnvState() !== savedEnvSnapshot;
      saveDirtyDot.classList.toggle("ok", !hasChanges);
      saveDirtyDot.classList.toggle("off", hasChanges);
      saveDirtyDot.title = hasChanges ? t("env.saveDirty") : t("env.saveClean");
    }}

    function captureSavedEnvSnapshot() {{
      savedEnvSnapshot = normalizedEnvState();
      updateSaveDirtyState();
    }}

    async function loadConfig() {{
      showToast(t("config.loading"), "info");
      const response = await fetch(apiUrl(configUrl), {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || t("config.loadError"));
      }}
      sapGuiExecutablePathInput.value = payload.sapGuiExecutablePath || "";
      systems.length = 0;
      (payload.systems || []).forEach((system) => systems.push(system));
      renderSystems();
      captureSavedEnvSnapshot();
      showToast(t("config.loaded"), "success");
    }}

    async function loadMcpClients() {{
      const response = await fetch(apiUrl(mcpStatusUrl), {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || t("mcp.loadError"));
      }}
      mcpClients.length = 0;
      (payload.clients || []).forEach((client) => mcpClients.push(client));
      renderMcpClients();
    }}

    function renderPlaywrightStatus(status) {{
      const tbody = document.getElementById("playwrightTableBody");
      lastPlaywrightStatus = status;
      tbody.innerHTML = "";
      const installed = status.browserInstalled;
      const disabled = !status.packageInstalled;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${{t("playwright.chromium")}}</td>
        <td><span class="signal"><span class="signal-dot ${{installed ? "ok" : "off"}}"></span>${{installed ? t("common.installed") : t("playwright.notInstalled")}}</span></td>
        <td>
          <button class="button secondary" type="button"
            data-playwright-action="browser"
            ${{installed || disabled ? "disabled" : ""}}
            title="${{disabled ? t("playwright.packageMissing") : ""}}">
            ${{installed ? t("common.installed") : "playwright install chromium"}}
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    }}

    async function loadPlaywrightStatus() {{
      const tbody = document.getElementById("playwrightTableBody");
      tbody.innerHTML = `<tr><td colspan="3" class="subtle">${{escapeHtml(t("playwright.checking"))}}</td></tr>`;
      try {{
        const response = await fetch(apiUrl(playwrightStatusUrl), {{ credentials: "same-origin" }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.message || t("playwright.errorCheck"));
        renderPlaywrightStatus(payload);
      }} catch (err) {{
        tbody.innerHTML = `<tr><td colspan="3" style="color:var(--danger);">${{err.message}}</td></tr>`;
      }}
    }}

    async function installPlaywright(action) {{
      const log = document.getElementById("playwrightLog");
      const tbody = document.getElementById("playwrightTableBody");
      const label = action === "package" ? "pip install playwright" : "playwright install chromium";

      log.style.display = "block";
      log.textContent = t("playwright.running", {{ label }});
      showToast(t("playwright.runningToast", {{ label }}), "info");
      tbody.querySelectorAll("button[data-playwright-action]").forEach((b) => b.disabled = true);

      try {{
        const response = await fetch(playwrightInstallUrl, {{
          method: "POST",
          credentials: "same-origin",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ action, language: currentLanguage }}),
        }});
        const payload = await response.json();
        log.textContent = (payload.output || "").trim() || (payload.message || t("playwright.noOutput"));
        if (!response.ok || !payload.success) {{
          log.style.color = "var(--danger)";
          showToast(payload.message || t("playwright.failed"), "error");
        }} else {{
          log.style.color = "var(--accent)";
          log.textContent += `\\n\\n${{t("playwright.completed")}}`;
          showToast(t("playwright.completedToast"), "success");
        }}
      }} catch (err) {{
        log.textContent = `Error: ${{err.message}}`;
        log.style.color = "var(--danger)";
        showToast(err.message || t("playwright.errorRun"), "error");
      }}
      await loadPlaywrightStatus();
    }}

    async function loadMemoryTree() {{
      const response = await fetch(apiUrl(memoryTreeUrl), {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || t("memory.loadTreeError"));
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
        summary.textContent = node.name || t("memory.folderFallback");
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
      button.innerHTML = `${{escapeHtml(node.name || t("memory.fileFallback"))}}<span class="file-meta">${{escapeHtml(node.extension || "")}}</span>`;
      return button;
    }}

    function renderMemoryTree() {{
      const filtered = filterMemoryNodes(memoryNodes, memoryFilterInput.value || "");
      memoryTreeEl.innerHTML = "";
      if (!filtered.length) {{
        memoryTreeEl.innerHTML = `<div class="subtle">${{escapeHtml(t("memory.noMatches"))}}</div>`;
        return;
      }}
      filtered.forEach((node) => memoryTreeEl.appendChild(renderMemoryNode(node, Boolean((memoryFilterInput.value || "").trim()))));
    }}

    function showMemoryPlaceholder() {{
      memoryViewerTitleEl.textContent = t("memory.document");
      memoryViewerMetaEl.textContent = t("memory.selectFile");
      memoryViewerEl.innerHTML = `<div class="viewer-placeholder">${{escapeHtml(t("memory.placeholder"))}}</div>`;
    }}

    async function openMemoryDocument(relativePath) {{
      selectedMemoryPath = relativePath;
      renderMemoryTree();
      const extension = String(relativePath.split(".").pop() || "").toLowerCase();
      memoryViewerTitleEl.textContent = relativePath.split("/").pop() || "Documento";
      memoryViewerMetaEl.textContent = relativePath;

      if (extension === "pdf") {{
        memoryViewerEl.innerHTML = `<iframe class="viewer-frame" src="${{apiUrl(memoryDocumentUrl)}}&relativePath=${{encodeURIComponent(relativePath)}}"></iframe>`;
        return;
      }}

      const response = await fetch(`${{apiUrl(memoryDocumentUrl)}}&relativePath=${{encodeURIComponent(relativePath)}}`, {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || t("memory.openError"));
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
          action,
          language: currentLanguage,
        }})
      }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || t("mcp.actionError"));
      }}
      await loadMcpClients();
      showToast(payload.message || t("mcp.actionApplied"), "success");
    }}

    function openEditor(index) {{
      editingIndex = index;
      const source = index === null
        ? {{ id: "", name: "", type: "", server: "", user: "", password: "", client: "", language: "EN", verify_ssl: false, sap_gui_connection_name: "", sap_webgui_url: "" }}
        : systems[index];

      dialogTitle.textContent = index === null ? t("env.addDialog") : t("env.editDialog");
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
      document.getElementById("sapWebguiUrl").value = source.sap_webgui_url || "";
      editorDialog.showModal();
    }}

    function renderSapLogonEntries() {{
      sapLogonTableBody.innerHTML = "";
      if (!sapLogonEntries.length) {{
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="5" style="color:#66604f;">${{escapeHtml(t("saplogon.noEntries"))}}</td>`;
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
          <td><button class="button secondary" type="button" data-import-index="${{index}}">${{t("common.use")}}</button></td>
        `;
        sapLogonTableBody.appendChild(row);
      }});
    }}

    async function loadSapLogonEntries() {{
      const response = await fetch(apiUrl(sapLogonUrl), {{ credentials: "same-origin" }});
      const payload = await response.json();
      if (!response.ok) {{
        throw new Error(payload.message || t("saplogon.loadError"));
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
        showToast(t("saplogon.basicApplied"), "success");
        return;
      }}

      showToast(t("saplogon.searchingPort"), "info");
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
            language: currentLanguage,
            sapLanguage: document.getElementById("systemLanguage").value.trim() || "EN"
          }})
        }});
        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(payload.message || t("saplogon.autoImportError"));
        }}
        document.getElementById("systemServer").value = payload.server || document.getElementById("systemServer").value || "";
        document.getElementById("sapGuiConnectionName").value = payload.connectionName || document.getElementById("sapGuiConnectionName").value || "";
        if (payload.defaultClient && !document.getElementById("systemClient").value.trim()) {{
          document.getElementById("systemClient").value = payload.defaultClient;
        }}
        showToast(payload.message || t("saplogon.autoImportSuccess"), "success");
      }} catch (error) {{
        console.error(error);
        showToast(error.message || t("saplogon.autoImportError"), "error");
      }}
    }}

    function removeSystem(index) {{
      systems.splice(index, 1);
      renderSystems();
      updateSaveDirtyState();
      showToast(t("env.connectionDeleted"), "warning");
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
        sap_webgui_url: document.getElementById("sapWebguiUrl").value.trim(),
      }};

      if (editingIndex === null) {{
        systems.push(system);
      }} else {{
        systems[editingIndex] = system;
      }}
      editorDialog.close();
      renderSystems();
      updateSaveDirtyState();
      showToast(t("env.connectionReady"), "success");
    }});

    document.getElementById("closeDialogButton").addEventListener("click", () => editorDialog.close());
    document.getElementById("closeSapLogonDialogButton").addEventListener("click", () => sapLogonDialog.close());
    [editorDialog, sapLogonDialog].forEach((dialog) => {{
      dialog.addEventListener("close", placeToastRegion);
      dialog.addEventListener("cancel", placeToastRegion);
    }});
    document.getElementById("addSystemButton").addEventListener("click", () => openEditor(null));
    sapGuiExecutablePathInput.addEventListener("input", updateSaveDirtyState);
    document.getElementById("openPortHelpButton").addEventListener("click", () => {{
      window.open(apiUrl(portHelpUrl), "_blank", "noopener,noreferrer");
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
        showToast(error.message || t("memory.openError"), "error");
      }}
    }});
    document.getElementById("importSapLogonButton").addEventListener("click", async () => {{
      try {{
        const runAutomation = window.confirm(
          t("saplogon.confirmAutomation")
        );
        const userValue = document.getElementById("systemUser").value.trim();
        const passwordValue = document.getElementById("systemPassword").value;
        sapLogonImportMode = runAutomation ? "auto" : "basic";
        if (runAutomation && (!userValue || !passwordValue)) {{
          showToast(t("saplogon.credentialsRequired"), "error");
          return;
        }}
        await loadSapLogonEntries();
        sapLogonDialog.showModal();
      }} catch (error) {{
        console.error(error);
        showToast(error.message || t("saplogon.loadError"), "error");
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
        showToast(error.message || t("mcp.actionError"), "error");
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
      showToast(t("config.saving"), "info");
      const response = await fetch(configUrl, {{
        method: "POST",
        credentials: "same-origin",
        headers: {{
          "Content-Type": "application/json"
        }},
        body: JSON.stringify({{
          sapGuiExecutablePath: sapGuiExecutablePathInput.value.trim(),
          systems,
          language: currentLanguage,
        }})
      }});

      const payload = await response.json();
      if (!response.ok) {{
        showToast(payload.message || t("config.saveError"), "error");
        return;
      }}
      showToast(payload.message || t("config.saved"), "success");
      await loadConfig();
      updateSaveDirtyState();
    }});

    document.getElementById("refreshPlaywrightButton").addEventListener("click", loadPlaywrightStatus);
    document.getElementById("playwrightTableBody").addEventListener("click", async (event) => {{
      const button = event.target.closest("button[data-playwright-action]");
      if (!button || button.disabled) return;
      await installPlaywright(button.dataset.playwrightAction);
    }});
    languageSelect.addEventListener("change", () => {{
      setLanguage(languageSelect.value);
    }});

    applyTranslations();
    showMemoryPlaceholder();
    Promise.all([loadConfig(), loadMcpClients(), loadMemoryTree(), loadPlaywrightStatus()]).catch((error) => {{
      console.error(error);
      showToast(error.message || t("config.loadError"), "error");
    }});
  </script>
</body>
</html>"""


_DASHBOARD_ROUTE_TEXT = {
    "es": {
        "load_config_failed": "No se pudo cargar la configuración del dashboard: {error}",
        "load_mcp_failed": "No se pudo cargar el estado MCP: {error}",
        "apply_mcp_failed": "No se pudo aplicar la acción MCP del dashboard: {error}",
        "load_memory_tree_failed": "No se pudo cargar el árbol de memoria: {error}",
        "load_memory_document_failed": "No se pudo cargar el documento de memoria: {error}",
        "config_saved": "Configuración guardada.",
        "save_config_failed": "No se pudo guardar la configuración del dashboard: {error}",
        "load_saplogon_failed": "No se pudieron cargar las entradas de SAP Logon: {error}",
        "port_detected": "Puerto {protocol} detectado automáticamente para {connection}: {server}",
        "fallback_connection": ". Se ha utilizado la entrada SAP GUI '{connection}' porque la seleccionada no se podía abrir automáticamente.",
        "default_client": ". Mandante detectado: {client}.",
        "import_saplogon_failed": "No se pudo importar automáticamente la entrada de SAP Logon: {error}",
        "check_playwright_failed": "No se pudo comprobar Playwright: {error}",
        "unknown_playwright_action": "Acción desconocida '{action}'. Usa 'package' o 'browser'.",
        "playwright_timeout": "El comando superó el tiempo límite de 5 minutos.",
        "run_install_failed": "No se pudo ejecutar el comando de instalación: {error}",
    },
    "en": {
        "load_config_failed": "Failed to load dashboard configuration: {error}",
        "load_mcp_failed": "Failed to load MCP client status: {error}",
        "apply_mcp_failed": "Failed to apply MCP dashboard action: {error}",
        "load_memory_tree_failed": "Failed to load memory tree: {error}",
        "load_memory_document_failed": "Failed to load memory document: {error}",
        "config_saved": "Dashboard configuration saved successfully.",
        "save_config_failed": "Failed to save dashboard configuration: {error}",
        "load_saplogon_failed": "Failed to load SAP Logon entries: {error}",
        "port_detected": "{protocol} port detected automatically for {connection}: {server}",
        "fallback_connection": ". SAP GUI entry '{connection}' was used because the selected one could not be opened automatically.",
        "default_client": ". Default client detected: {client}.",
        "import_saplogon_failed": "Failed to import the SAP Logon entry automatically: {error}",
        "check_playwright_failed": "Failed to check Playwright: {error}",
        "unknown_playwright_action": "Unknown action '{action}'. Use 'package' or 'browser'.",
        "playwright_timeout": "The command exceeded the 5 minute timeout.",
        "run_install_failed": "Failed to run install command: {error}",
    },
}


def _dashboard_lang(value: str | None) -> str:
    return "en" if str(value or "").strip().lower() == "en" else "es"


def _dashboard_request_lang(request) -> str:
    return _dashboard_lang(request.query_params.get("lang"))


def _dashboard_payload_lang(payload: dict) -> str:
    return _dashboard_lang(payload.get("language"))


def _route_text(lang: str, key: str, **kwargs) -> str:
    return _DASHBOARD_ROUTE_TEXT[_dashboard_lang(lang)][key].format(**kwargs)


mcp = FastMCP(name="ABAP Tools - MCP Server", version="1.0.0", lifespan=abap_lifespan)


@mcp.custom_route(HTTP_DASHBOARD_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_page(_request):
    """Serve the lightweight dashboard used to manage SAP systems in the .env file."""
    return HTMLResponse(_dashboard_html())


@mcp.custom_route(HTTP_DASHBOARD_CONFIG_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_config(_request):
    """Return the dashboard-managed SAP configuration as JSON."""
    lang = _dashboard_request_lang(_request)
    try:
        return JSONResponse(get_dashboard_config())
    except Exception as exc:
        return JSONResponse({"message": _route_text(lang, "load_config_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MCP_STATUS_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_mcp_status(_request):
    """Return the MCP client status table shown in the dashboard."""
    lang = _dashboard_request_lang(_request)
    try:
        return JSONResponse(dashboard_get_mcp_status_data(lang))
    except Exception as exc:
        return JSONResponse({"message": _route_text(lang, "load_mcp_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MCP_ACTION_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_apply_mcp_action_route(request):
    """Insert, adjust or delete the ABAP MCP entry in one local client configuration."""
    try:
        payload = await request.json()
        lang = _dashboard_payload_lang(payload)
        client_id = str(payload.get("clientId", "") or "").strip().lower()
        action = str(payload.get("action", "") or "").strip().lower()
        return JSONResponse(dashboard_apply_mcp_action(client_id, action, lang))
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"message": _route_text(locals().get("lang", "es"), "apply_mcp_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MEMORY_TREE_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_memory_tree(_request):
    """Return the local documents tree shown in the dashboard memory tab."""
    lang = _dashboard_request_lang(_request)
    try:
        return JSONResponse(_memory_tree_payload())
    except Exception as exc:
        return JSONResponse({"message": _route_text(lang, "load_memory_tree_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_MEMORY_DOCUMENT_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_get_memory_document(request):
    """Return one local memory document either as markdown JSON or as a PDF file response."""
    lang = _dashboard_request_lang(request)
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
        return JSONResponse({"message": _route_text(lang, "load_memory_document_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_PORT_HELP_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_port_help_page(_request):
    """Serve the SAP GUI tutorial showing how to find the HTTPS port in SMICM."""
    return HTMLResponse(render_dashboard_port_help_html(_dashboard_request_lang(_request)))


@mcp.custom_route(HTTP_DASHBOARD_CONFIG_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_save_config(request):
    """Persist the dashboard-managed SAP configuration back into the .env file."""
    try:
        payload = await request.json()
        lang = _dashboard_payload_lang(payload)
        systems = payload.get("systems", [])
        sap_gui_executable_path = str(payload.get("sapGuiExecutablePath", "") or "")
        update_dashboard_config(systems, sap_gui_executable_path)
        return JSONResponse({"message": _route_text(lang, "config_saved")})
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"message": _route_text(locals().get("lang", "es"), "save_config_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_SAPLOGON_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_list_saplogon_entries(_request):
    """Return the SAP Logon entries discovered from the local SAP UI Landscape XML files."""
    lang = _dashboard_request_lang(_request)
    try:
        return JSONResponse(list_sap_logon_entries())
    except Exception as exc:
        return JSONResponse({"message": _route_text(lang, "load_saplogon_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_SAPLOGON_IMPORT_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_import_saplogon_entry(request):
    """Resolve the HTTPS endpoint for one SAP Logon entry through a temporary SAP GUI session."""
    try:
        payload = await request.json()
        lang = _dashboard_payload_lang(payload)
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
            language=str(payload.get("sapLanguage", "") or "EN").strip() or "EN",
        )
        protocol = str(result.get("protocol", "") or "").strip().lower()
        protocol_label = "HTTPS" if protocol == "https" else "HTTP"
        message = _route_text(lang, "port_detected", protocol=protocol_label, connection=connection_name, server=result["server"])
        used_connection_name = str(result.get("connectionName", "") or "").strip()
        if used_connection_name and used_connection_name != connection_name:
            message += _route_text(lang, "fallback_connection", connection=used_connection_name)
        default_client = str(result.get("defaultClient", "") or "").strip()
        if default_client:
            message += _route_text(lang, "default_client", client=default_client)
        return JSONResponse({
            **result,
            "message": message,
        })
    except ValueError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"message": str(exc)}, status_code=409)
    except Exception as exc:
        return JSONResponse({"message": _route_text(locals().get("lang", "es"), "import_saplogon_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_PLAYWRIGHT_STATUS_PATH, methods=["GET"], include_in_schema=False)
async def dashboard_playwright_status(_request):
    """Return the installation status of the Playwright package and Chromium browser."""
    lang = _dashboard_request_lang(_request)
    try:
        return JSONResponse(await asyncio.to_thread(_get_playwright_status))
    except Exception as exc:
        return JSONResponse({"message": _route_text(lang, "check_playwright_failed", error=str(exc))}, status_code=500)


@mcp.custom_route(HTTP_DASHBOARD_PLAYWRIGHT_INSTALL_PATH, methods=["POST"], include_in_schema=False)
async def dashboard_playwright_install(request):
    """Run pip install playwright or playwright install chromium in a background thread."""
    import subprocess
    import sys
    try:
        payload = await request.json()
        lang = _dashboard_payload_lang(payload)
        action = str(payload.get("action", "") or "").strip()
        if action == "package":
            cmd = [sys.executable, "-m", "pip", "install", "playwright"]
        elif action == "browser":
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
        else:
            return JSONResponse({"message": _route_text(lang, "unknown_playwright_action", action=action)}, status_code=400)

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return JSONResponse({
            "success": result.returncode == 0,
            "output": result.stdout + result.stderr,
            "returnCode": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return JSONResponse({"success": False, "output": _route_text(locals().get("lang", "es"), "playwright_timeout"), "returnCode": -1})
    except Exception as exc:
        return JSONResponse({"message": _route_text(locals().get("lang", "es"), "run_install_failed", error=str(exc))}, status_code=500)


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

# region Internals
@mcp.tool()
def abap_skills_install(
    projectPath: str = Field(..., description="Absolute local project root path where the client project should be configured. The agent may infer this from the active workspace or user context."),
    client: Literal["opencode"] = Field(..., description="Target client. The user must explicitly provide this value before calling the tool. Supported value in v1: opencode."),
    scope: Literal["project"] = Field(..., description="Installation scope. The user must explicitly provide this value before calling the tool. Supported value in v1: project."),
    overwrite: bool = Field(True, description="When true, replace previously installed supported SAP skills in the target project. Defaults to true."),
) -> SkillsInstallResponse:
    """Install bundled SAP skills into a supported client project.

    In v1 this supports OpenCode project-level skills at
    <projectPath>/.opencode/skills/<skill-name>/ and intentionally omits
    agents/openai.yaml metadata from the installed copies.
    """
    return install_skills(projectPath, client, scope, overwrite)


@mcp.tool()
def internals_object_lock_probe(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the object lock should be probed."),
    objectUri: str = Field(..., description="Absolute ADT object URI to lock and immediately unlock, for example /sap/bc/adt/programs/programs/ztest.")
) -> ObjectLockProbeResponse:
    """Lock and immediately unlock one ADT object URI to inspect the CTS request SAP reports for modifications."""
    return probe_object_lock(systemId, objectUri)


@mcp.tool()
def workflow_start(
    workflow: str = Field(..., description="Workflow name to start. Supported value in v1: sap_repository_change."),
    projectPath: str = Field(..., description="Absolute local project root path targeted by the workflow."),
    task: str = Field(..., description="User task the workflow is coordinating."),
    input: dict[str, Any] | None = Field(None, description="Optional initial workflow input JSON."),
) -> WorkflowResponse:
    """Start a persistent JSON-driven workflow and return the next agent instruction."""
    return call_workflow_start(workflow, projectPath, task, input)


@mcp.tool()
def workflow_continue(
    workflowId: str = Field(..., description="Workflow id returned by workflow_start."),
    input: dict[str, Any] = Field(..., description="Input JSON matching the previous expectedInputSchema."),
) -> WorkflowResponse:
    """Continue a persistent workflow with agent-provided JSON input."""
    return call_workflow_continue(workflowId, input)


@mcp.tool()
def workflow_status(
    workflowId: str = Field(..., description="Workflow id returned by workflow_start."),
) -> WorkflowResponse:
    """Return the current status and last output for one workflow."""
    return call_workflow_status(workflowId)


@mcp.tool()
def workflow_log(
    workflowId: str = Field(..., description="Workflow id returned by workflow_start."),
) -> WorkflowLogResponse:
    """Return the persisted JSON event log for one workflow run."""
    return call_workflow_log(workflowId)


@mcp.tool()
def workflow_cancel(
    workflowId: str = Field(..., description="Workflow id returned by workflow_start."),
) -> WorkflowResponse:
    """Cancel a persistent workflow run and record the cancellation in the workflow log."""
    return call_workflow_cancel(workflowId)
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
    name: str = Field(..., description="Technical ABAP include name to lock. Low-level operation for manual workflows only; do not call it before source_program_include_update or source_program_include_write_from_file because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP include name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP include name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function group include name to lock. Low-level operation for manual workflows only; do not call it before source_function_include_update or source_function_include_write_from_file because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP function group include name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function group include name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function module name to lock. Low-level operation for manual workflows only; do not call it before source_function_module_update or source_function_module_write_from_file because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP function module name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function module name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function group name to lock. Low-level operation for manual workflows only; do not call it before source_function_group_update or source_function_group_write_from_file because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP function group name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function group name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP function group name whose text symbols should be updated. This tool manages the required symbols-resource lock and unlock internally; do not call separate lock or unlock tools."),
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
    name: str = Field(..., description="Technical ABAP function group name whose text symbols should be updated. This tool manages the required symbols-resource lock and unlock internally; do not call separate lock or unlock tools."),
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
    name: str = Field(..., description="Technical ABAP interface name to lock. Low-level operation for manual workflows only; do not call it before source_interface_update or source_interface_write_from_file because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP interface name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP interface name to update. This tool manages the required lock and unlock internally; do not call the separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical ABAP class name to lock. Low-level operation for manual workflows only; do not call it before source_class_update, source_class_write_from_file, symbols, or testclasses mutation tools because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP class name to update. This tool manages the required lock and unlock internally; do not call source_class_lock or source_class_unlock before or after it."),
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
    name: str = Field(..., description="Technical ABAP class name to update. This tool manages the required lock and unlock internally; do not call source_class_lock or source_class_unlock before or after it."),
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
    name: str = Field(..., description="Technical ABAP class name whose text symbols should be updated. This tool manages the required symbols-resource lock and unlock internally; do not call source_class_lock or source_class_unlock."),
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
    name: str = Field(..., description="Technical ABAP class name whose text symbols should be updated. This tool manages the required symbols-resource lock and unlock internally; do not call source_class_lock or source_class_unlock."),
    filePath: str = Field(..., description="Absolute local file path of the raw text symbols to upload."),
) -> FileTransferResponse:
    """Upload text symbols from a local file to one existing ABAP class through its `/source/symbols` endpoint. The tool locks the class, writes the new symbols, and unlocks it automatically."""
    return call_class_symbols_write_from_file(systemId, name, filePath)


@mcp.tool()
def source_class_testclasses_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be created."),
    className: str = Field(..., description="Technical ABAP class name that will own the testclasses include. Use this tool only when source_class_testclasses_read confirms that the include does not exist. Creation locks and unlocks the parent class internally because the testclasses include cannot be locked before it exists; do not call source_class_lock or source_class_unlock. After creation, call source_class_testclasses_update or source_class_testclasses_write_from_file to store the test source."),
    transportNumber: str = Field("", description="Transport request number to forward when the class belongs to a transportable package. Supply it during creation and again during the subsequent update when SAP requires the change to be recorded in a transport."),
) -> ClassTestclassesCreateResponse:
    """Create the empty `testclasses` include of one existing ABAP class. Agent workflow: read first; if the include is missing, call this tool once and then call update or write-from-file with the test source. Do not call manual lock or unlock tools: creation locks the parent class internally because the include does not exist yet."""
    return call_class_testclasses_create(systemId, className, transportNumber)


@mcp.tool()
def source_class_testclasses_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be read."),
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include. Agents can call this before writing to determine whether they must create the include first."),
) -> ClassTestclassesReadResponse:
    """Read the raw source code of the `testclasses` include of one ABAP class. If it is missing, call create once before update or write-from-file."""
    return call_class_testclasses_read(systemId, className)


@mcp.tool()
def source_class_testclasses_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the class testclasses include should be updated."),
    className: str = Field(..., description="Technical ABAP class name that owns the existing testclasses include. If the include does not exist, call source_class_testclasses_create once first. This tool locks and unlocks the testclasses include internally; do not call source_class_lock or source_class_unlock before or after it."),
    request: ClassTestclassesUpdateRequest = Field(..., description="Full ABAP source code to store in the `testclasses` include."),
    transportNumber: str = Field("", description="Transport request number to forward when the class belongs to a transportable package."),
) -> ClassTestclassesUpdateResponse:
    """Update the raw source code of the `testclasses` include of one ABAP class. The tool locks the testclasses include, writes the new source, and unlocks it automatically."""
    return call_class_testclasses_update(systemId, className, request, transportNumber)


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
    className: str = Field(..., description="Technical ABAP class name that owns the existing testclasses include. If the include does not exist, call source_class_testclasses_create once first. This tool locks and unlocks the testclasses include internally; do not call source_class_lock or source_class_unlock before or after it."),
    filePath: str = Field(..., description="Absolute local file path of the raw source code to upload."),
    transportNumber: str = Field("", description="Transport request number to forward when the class belongs to a transportable package."),
) -> FileTransferResponse:
    """Upload the `testclasses` include of one ABAP class from a local file. The tool locks the testclasses include, writes the new source, and unlocks it automatically."""
    return call_class_testclasses_write_from_file(systemId, className, filePath, transportNumber)
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
    name: str = Field(..., description="Technical ABAP program name to lock. Low-level operation for manual workflows only; do not call it before source_program_update, source_program_write_from_file, or symbols mutation tools because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical ABAP program name to update. This tool manages the required lock and unlock internally; do not call source_program_lock or source_program_unlock before or after it."),
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
    name: str = Field(..., description="Technical ABAP program name to update. This tool manages the required lock and unlock internally; do not call source_program_lock or source_program_unlock before or after it."),
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
    name: str = Field(..., description="Technical ABAP program name whose text symbols should be updated. This tool manages the required symbols-resource lock and unlock internally; do not call source_program_lock or source_program_unlock."),
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
    name: str = Field(..., description="Technical ABAP program name whose text symbols should be updated. This tool manages the required symbols-resource lock and unlock internally; do not call source_program_lock or source_program_unlock."),
    filePath: str = Field(..., description="Absolute local file path of the raw text symbols to upload."),
) -> FileTransferResponse:
    """Upload text symbols from a local file to one existing ABAP program through its `/source/symbols` endpoint. The tool locks the program, writes the new symbols, and unlocks it automatically."""
    return call_program_symbols_write_from_file(systemId, name, filePath)
# endregion

# region Documentation
@mcp.tool()
def docu_abap_language_help(
    systemId: str = Field(..., description="Identifier of the configured SAP system where ABAP keyword documentation should be retrieved."),
    request: DocuAbapLanguageHelpRequest = Field(..., description="ABAP editor buffer and ADT 1-based #start/#end source range of the selected keyword or language construct."),
) -> DocuAbapLanguageHelpResponse:
    """Retrieve ABAP keyword documentation for a selected ABAP source range through /sap/bc/adt/docu/abap/langu."""
    return call_docu_abap_language_help(systemId, request)
# endregion

# region Code Completion
@mcp.tool()
def codecompletion_proposals(
    systemId: str = Field(..., description="Identifier of the configured SAP system where ABAP code completion should be calculated."),
    request: CodeCompletionProposalsRequest = Field(..., description="ABAP editor buffer and cursor position for completion. Set includeElementInfo to true to also fetch ADT element information in the same call."),
) -> CodeCompletionProposalsResponse:
    """Calculate ABAP ADT code completion proposals and optionally include element info for a requested source position."""
    return call_codecompletion_proposals(systemId, request)
# endregion

# region Navigation
@mcp.tool()
def navigation_target(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP source should be resolved."),
    request: NavigationTargetRequest = Field(..., description="ABAP editor buffer and 1-based source range of the selected symbol. Resolves the symbol definition through /sap/bc/adt/navigation/target."),
) -> NavigationTargetResponse:
    """Resolve the ADT navigation target for a selected ABAP symbol, equivalent to Eclipse ADT Go to Definition."""
    return call_navigation_target(systemId, request)
# endregion

# region Info Repository
@mcp.tool()
def info_repository_search(systemId: str = Field(..., description="Identifier of the configured SAP system to query."),
           searchTerm: str = Field(..., description="Search pattern for the SAP repository information system. Supports wildcards such as '*' and can match object names or descriptions."),
           objectType: str = Field("", description="Optional 4-character SAP object type filter such as PROG, CLAS, FUGR, TABL, DTEL, DOMA, INTF, or DDLS.")) -> InfoRepositorySearchResponse:
    """Search the SAP repository information system of one configured SAP system for development objects."""
    return call_info_repository_search(systemId, searchTerm, objectType=objectType)


@mcp.tool()
def info_repository_usage_references(
    systemId: str = Field(..., description="Identifier of the configured SAP system to query."),
    request: InfoRepositoryUsageReferencesRequest = Field(..., description="ADT source selection for the ABAP symbol whose where-used references should be resolved."),
) -> InfoRepositoryUsageReferencesResponse:
    """Run ADT where-used usageReferences for a selected ABAP symbol and return the reference tree plus snippet object identifiers."""
    return call_info_repository_usage_references(systemId, request)


@mcp.tool()
def info_repository_usage_snippets(
    systemId: str = Field(..., description="Identifier of the configured SAP system to query."),
    request: InfoRepositoryUsageSnippetsRequest = Field(..., description="Usage reference object identifiers returned by info_repository_usage_references."),
) -> InfoRepositoryUsageSnippetsResponse:
    """Fetch ADT where-used source snippets for one or more usage reference object identifiers."""
    return call_info_repository_usage_snippets(systemId, request)


@mcp.tool()
def info_repository_where_used(
    systemId: str = Field(..., description="Identifier of the configured SAP system to query."),
    request: InfoRepositoryUsageReferencesRequest = Field(..., description="ADT source selection for the ABAP symbol whose complete where-used result should be returned."),
) -> InfoRepositoryWhereUsedResponse:
    """Run a complete ADT where-used lookup by calling usageReferences and then usageSnippets automatically."""
    return call_info_repository_where_used(systemId, request)
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
    transportNumber: str = Field(..., description="Transport request number to update. This tool manages the required transport lock and unlock internally; do not perform a separate lock or unlock."),
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
    transportNumber: str = Field(..., description="Transport request number to update. This tool manages the required transport lock and unlock internally; do not perform a separate lock or unlock."),
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
    name: str = Field(..., description="Technical package name to update. This tool manages the required package lock and unlock internally; do not perform a separate lock or unlock."),
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
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings will be updated. This tool manages the required settings lock and unlock internally; do not call separate lock or unlock tools."),
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
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings will be uploaded. This tool manages the required settings lock and unlock internally; do not call separate lock or unlock tools."),
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
    name: str = Field(..., description="Technical name of the DDIC table to update. This tool manages the required lock and unlock internally; do not call separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical name of the DDIC table to upload. This tool manages the required lock and unlock internally; do not call separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical name of the DDIC data element to update. This tool manages the required lock and unlock internally; do not call separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical name of the DDIC data element to upload. This tool manages the required lock and unlock internally; do not call separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical name of the DDIC domain to update. This tool manages the required lock and unlock internally; do not call separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical name of the DDIC domain to upload. This tool manages the required lock and unlock internally; do not call separate lock or unlock tools before or after it."),
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
    name: str = Field(..., description="Technical name of the CDS DDL source to lock. Low-level operation for manual workflows only; do not call it before ddic_ddl_source_update or ddic_ddl_source_write_from_file because those tools manage locking internally.")
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
    name: str = Field(..., description="Technical name of the CDS DDL source to update. This tool manages the required lock and unlock internally; do not call ddic_ddl_source_lock or ddic_ddl_source_unlock before or after it."),
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
    name: str = Field(..., description="Technical name of the CDS DDL source to update. This tool manages the required lock and unlock internally; do not call ddic_ddl_source_lock or ddic_ddl_source_unlock before or after it."),
    filePath: str = Field(..., description="Absolute local file path of the CDS source to upload. The file must keep the same format returned by ddic_ddl_source_read_to_file."),
    transportNumber: str = Field("", description="Transport request number to forward when the DDL source belongs to a transportable package. Leave empty for local objects such as $TMP.")
) -> FileTransferResponse:
    """Upload raw CDS source code from a local file to one existing CDS DDL source through its `/source/main` endpoint. The tool locks the DDL source, writes the new source, and unlocks it automatically."""
    return call_ddic_ddl_source_write_from_file(systemId, name, filePath, transportNumber)
# endregion

# region SAP WebGUI
@mcp.tool()
def sap_webgui_sessions_list() -> SapWebguiSessionListResponse:
    """List all SAP WebGUI browser sessions currently open in the MCP server.

    Returns the internal webguiSessionId, the SAP system identifier, and the
    current browser URL for each open session."""
    return call_sap_webgui_sessions_list()


@mcp.tool()
def sap_webgui_session_open(
    systemId: str = Field(..., description="Identifier of the configured SAP system to open. The system must have 'sap_webgui_url' configured in the dashboard.")
) -> SapWebguiSessionOpenResponse:
    """Open a Chromium browser window, navigate to the SAP WebGUI URL, and log in automatically.

    Credentials and the WebGUI URL are read from the server configuration — the AI
    never has access to them. The returned webguiSessionId identifies the session
    for subsequent Playwright operations and must be passed to sap_webgui_session_close
    when done."""
    return call_sap_webgui_session_open(systemId)


@mcp.tool()
def sap_webgui_session_close(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session to close. Returned by sap_webgui_session_open.")
) -> SapWebguiSessionCloseResponse:
    """Close one SAP WebGUI browser session and remove it from the MCP server registry.

    The underlying Chromium page is closed. If the page was already gone the
    alreadyClosed flag in the response will be True."""
    return call_sap_webgui_session_close(webguiSessionId)


@mcp.tool()
def sap_webgui_snapshot(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open.")
) -> SapWebguiSnapshotResponse:
    """Capture the accessibility tree of the current SAP WebGUI page.

    Returns the full UI structure as a JSON string. Use this to discover element
    selectors and understand the current screen state before performing actions.
    Prefer this over sap_webgui_screenshot when you need to interact with elements."""
    return call_sap_webgui_snapshot(webguiSessionId)


@mcp.tool()
def sap_webgui_screenshot(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    fullPage: bool = Field(False, description="When True captures the full scrollable page. When False (default) captures only the visible viewport.")
) -> SapWebguiScreenshotResponse:
    """Take a PNG screenshot of the current SAP WebGUI page.

    Returns the image encoded as base64. Use this for visual confirmation of the
    current screen state. For element interaction, use sap_webgui_snapshot instead."""
    return call_sap_webgui_screenshot(webguiSessionId, fullPage)


@mcp.tool()
def sap_webgui_click(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    target: str = Field(..., description="CSS selector or element reference identifying the element to click. Obtain from sap_webgui_snapshot."),
    button: str = Field("left", description="Mouse button to use: 'left' (default), 'right', or 'middle'."),
    doubleClick: bool = Field(False, description="When True performs a double-click instead of a single click."),
    modifiers: list[str] = Field(default_factory=list, description="Keyboard modifiers to hold during the click: 'Alt', 'Control', 'Meta', 'Shift'.")
) -> SapWebguiActionResponse:
    """Click an element on the current SAP WebGUI page.

    Use sap_webgui_snapshot first to obtain the exact element selector.
    Returns the current URL after the click so you can verify navigation."""
    return call_sap_webgui_click(webguiSessionId, target, button, doubleClick, modifiers)


@mcp.tool()
def sap_webgui_type(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    target: str = Field(..., description="CSS selector or element reference identifying the input field. Obtain from sap_webgui_snapshot."),
    text: str = Field(..., description="Text to type into the field."),
    slowly: bool = Field(False, description="When True types one character at a time, useful for fields with key-press handlers. Default is False (fill all at once)."),
    submit: bool = Field(False, description="When True presses Enter after typing, useful for search fields and transaction boxes.")
) -> SapWebguiActionResponse:
    """Type text into a field on the current SAP WebGUI page.

    Use slowly=True for SAP fields with auto-complete or value-help triggers.
    Use submit=True to confirm input without a separate sap_webgui_press_key call."""
    return call_sap_webgui_type(webguiSessionId, target, text, slowly, submit)


@mcp.tool()
def sap_webgui_press_key(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    key: str = Field(..., description="Key name to press, e.g. 'Enter', 'Escape', 'F4', 'F8', 'Tab', 'ArrowDown'. Follows Playwright key naming conventions.")
) -> SapWebguiActionResponse:
    """Press a keyboard key on the current SAP WebGUI page.

    Essential for SAP navigation: Enter to confirm, F4 for value help, F8 to execute,
    Escape to cancel, Tab to move between fields."""
    return call_sap_webgui_press_key(webguiSessionId, key)


@mcp.tool()
def sap_webgui_fill_form(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    fields: list[SapWebguiFillFormField] = Field(..., description="List of fields to fill. Each field requires target (selector), name (label), type (textbox/checkbox/radio/combobox) and value.")
) -> SapWebguiFillFormResponse:
    """Fill multiple form fields at once on the current SAP WebGUI page.

    More efficient than calling sap_webgui_type for each field individually.
    Use sap_webgui_snapshot first to discover selectors and field types."""
    return call_sap_webgui_fill_form(webguiSessionId, fields)


@mcp.tool()
def sap_webgui_navigate(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    url: str = Field(..., description="Full URL to navigate to, e.g. a SAP WebGUI transaction URL.")
) -> SapWebguiActionResponse:
    """Navigate the SAP WebGUI browser session to a specific URL.

    Use this to jump directly to a SAP transaction URL without manual navigation.
    Returns the actual URL after navigation (which may differ due to SAP redirects)."""
    return call_sap_webgui_navigate(webguiSessionId, url)


@mcp.tool()
def sap_webgui_recording_start(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open."),
    outputFile: str = Field("recording.ts", description="Path where the TypeScript script will be written in real time. Relative paths are resolved from the working directory of the MCP server process.")
) -> SapWebguiRecordingStartResponse:
    """Start recording user actions in the SAP WebGUI browser as a Playwright TypeScript script.

    Uses Playwright's built-in recorder (the same engine as `playwright codegen`)
    on the existing browser session. Actions are written to outputFile in real time
    as the user interacts with the browser. Call sap_webgui_recording_stop when done
    to disable the recorder and retrieve the generated script."""
    return call_sap_webgui_recording_start(webguiSessionId, outputFile)


@mcp.tool()
def sap_webgui_recording_stop(
    webguiSessionId: str = Field(..., description="Internal MCP identifier of the SAP WebGUI session. Returned by sap_webgui_session_open.")
) -> SapWebguiRecordingStopResponse:
    """Stop the active Playwright recording session and return the generated TypeScript script.

    Disables the recorder and reads the TypeScript file written during recording.
    The script is returned both as a string in the response and kept on disk at outputFile.
    After this call the browser continues to work normally."""
    return call_sap_webgui_recording_stop(webguiSessionId)
# endregion


# region Data Preview
@mcp.tool()
def datapreview_metadata(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC entity exists. Call login first for this system."),
    ddicEntityName: str = Field(..., description="Technical DDIC table, database view or CDS SQL view name to inspect, e.g. USR01. The tool calls /sap/bc/adt/datapreview/ddic/<entity>/metadata.")
) -> DataPreviewMetadataResponse:
    """Read ADT data preview metadata for one DDIC entity.

    Use this to discover available fields, types, DDIC descriptions and lengths before
    building a data preview query."""
    return call_datapreview_metadata(systemId, ddicEntityName)


@mcp.tool()
def datapreview_table_contents(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC entity exists. Call login first for this system."),
    ddicEntityName: str = Field(..., description="Technical DDIC table, database view or CDS SQL view name to read, e.g. USR01. Used as ddicEntityName on the ADT datapreview/ddic endpoint."),
    rowNumber: int = Field(100, description="Maximum number of rows SAP should return. This is passed as ADT rowNumber, not applied client-side."),
    where: str = Field("", description="Optional ABAP Open SQL WHERE condition without the WHERE keyword, e.g. BNAME = 'DEVELOPER'. Use ABAP Open SQL syntax, not database-specific SQL. Used only when sqlQuery is empty."),
    sqlQuery: str = Field("", description="Optional full ABAP Open SQL SELECT to send to the DDIC data preview endpoint. Use ABAP Open SQL syntax, e.g. table~field notation; avoid database-specific SQL. Leave empty to let the tool fetch metadata and generate SELECT <all fields> FROM <entity> plus optional where."),
    outputFormat: str = Field("md", description="Inline output format: raw, md or csv. raw returns SAP XML; md/csv return row-oriented table text and include parsed field metadata.")
) -> DataPreviewResultResponse:
    """Read DDIC data preview contents and return them as raw XML, Markdown or CSV.

    Markdown and CSV outputs include field metadata in a separate response property so
    an AI can reason over column names, types and lengths."""
    return call_datapreview_table_contents(systemId, ddicEntityName, rowNumber, where, sqlQuery, outputFormat)


@mcp.tool()
def datapreview_run_query(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the query should run. Call login first for this system."),
    sqlQuery: str = Field(..., description="Freestyle ABAP Open SQL SELECT statement to execute through /sap/bc/adt/datapreview/freestyle. Use ABAP Open SQL syntax, not database-specific SQL. Use this for joins, aliases, calculations or arbitrary SELECTs supported by ABAP Open SQL."),
    rowNumber: int = Field(100, description="Maximum number of rows SAP should return. This is passed as ADT rowNumber, not applied client-side."),
    outputFormat: str = Field("md", description="Inline output format: raw, md or csv. raw returns SAP XML; md/csv return row-oriented table text and include parsed field metadata.")
) -> DataPreviewResultResponse:
    """Run a freestyle ABAP Open SQL data preview query and return raw XML, Markdown or CSV."""
    return call_datapreview_run_query(systemId, sqlQuery, rowNumber, outputFormat)


@mcp.tool()
def datapreview_table_contents_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC entity exists. Call login first for this system."),
    ddicEntityName: str = Field(..., description="Technical DDIC table, database view or CDS SQL view name to read, e.g. USR01."),
    filePath: str = Field(..., description="Destination file path for the exported data, e.g. usr01.csv, usr01.md or usr01.xlsx. Relative paths are resolved from the MCP server working directory."),
    rowNumber: int = Field(100, description="Maximum number of rows SAP should return. This is passed as ADT rowNumber, not applied client-side."),
    where: str = Field("", description="Optional ABAP Open SQL WHERE condition without the WHERE keyword, e.g. BNAME = 'DEVELOPER'. Use ABAP Open SQL syntax, not database-specific SQL. Used only when sqlQuery is empty."),
    sqlQuery: str = Field("", description="Optional full ABAP Open SQL SELECT to send to the DDIC data preview endpoint. Use ABAP Open SQL syntax, e.g. table~field notation; avoid database-specific SQL. Leave empty to let the tool fetch metadata and generate SELECT <all fields> FROM <entity> plus optional where."),
    outputFormat: str = Field("csv", description="File output format: raw, md, csv or xlsx. md/csv write a JSON sidecar '<filePath>.metadata'; xlsx embeds data, metadata and query details in workbook sheets.")
) -> DataPreviewFileResponse:
    """Read DDIC data preview contents and write them to a local file.

    When outputFormat is md or csv, the field metadata is written as JSON to
    '<filePath>.metadata'. XLSX stores metadata inside the workbook."""
    return call_datapreview_table_contents_to_file(systemId, ddicEntityName, filePath, rowNumber, where, sqlQuery, outputFormat)


@mcp.tool()
def datapreview_run_query_to_file(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the query should run. Call login first for this system."),
    sqlQuery: str = Field(..., description="Freestyle ABAP Open SQL SELECT statement to execute through /sap/bc/adt/datapreview/freestyle. Use ABAP Open SQL syntax, not database-specific SQL. Use this for joins, aliases, calculations or arbitrary SELECTs supported by ABAP Open SQL."),
    filePath: str = Field(..., description="Destination file path for the exported data, e.g. query.csv, query.md or query.xlsx. Relative paths are resolved from the MCP server working directory."),
    rowNumber: int = Field(100, description="Maximum number of rows SAP should return. This is passed as ADT rowNumber, not applied client-side."),
    outputFormat: str = Field("csv", description="File output format: raw, md, csv or xlsx. md/csv write a JSON sidecar '<filePath>.metadata'; xlsx embeds data, metadata and query details in workbook sheets.")
) -> DataPreviewFileResponse:
    """Run a freestyle ABAP Open SQL data preview query and write the result to a local file."""
    return call_datapreview_run_query_to_file(systemId, sqlQuery, filePath, rowNumber, outputFormat)
# endregion


# region Class Run
@mcp.tool()
def classrun_run(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP class should be executed."),
    className: str = Field(..., description="Technical name of the executable ABAP class to run, e.g. 'YJRS_RUN_TEST'.")
) -> ClassRunResponse:
    """Execute an ABAP class through the ADT classrun endpoint and return its plain-text console output.

    This mirrors Eclipse ADT Run As > ABAP Application (Console) and performs
    `POST /sap/bc/adt/oo/classrun/{className}` with `Accept: text/plain`.
    Use it for classes that implement the runnable ABAP application entry point."""
    return call_classrun_run(systemId, className)
# endregion


# region Check Runs
@mcp.tool()
def checkrun_syntax_check(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the syntax check should run."),
    objectUri: str = Field(..., description="ADT repository object URI of the object to check, e.g. '/sap/bc/adt/oo/classes/zcl_my_class' or '/sap/bc/adt/ddic/ddl/sources/yjrs_cds_0001'."),
    sourceUri: str = Field(..., description="ADT source URI of the content to check, e.g. '/sap/bc/adt/oo/classes/zcl_my_class/source/main'. Typically the objectUri with '/source/main' appended."),
    source: str = Field(..., description="Full source code to syntax-check. The content is base64-encoded before being sent to SAP, so any valid Unicode text is accepted."),
    version: str = Field("inactive", description="Object version to check against: 'inactive' to check the provided source before activation, 'active' to check against the currently active version.")
) -> CheckRunResponse:
    """Run the SAP ABAP syntax checker for one repository object through the ADT checkruns endpoint.

    The source content is sent to SAP base64-encoded and checked without saving.
    The response contains per-message detail including source position (line and column)
    for each error or warning, which can be correlated against the source to locate issues."""
    return call_checkrun(systemId, objectUri, sourceUri, source, version)
# endregion


# region ABAP Unit
@mcp.tool()
def abapunit_run(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the ABAP Unit tests should be executed."),
    objectUris: list[str] = Field(..., description="List of ADT repository object URIs whose unit tests should be run (e.g. '/sap/bc/adt/oo/classes/zcl_my_class')."),
    withCoverage: bool = Field(True, description="When True the SAP system collects code coverage data alongside the test run. Set to False if you only need pass/fail results.")
) -> AbapUnitRunResponse:
    """Execute ABAP Unit tests for one or more repository objects and return aggregated pass/fail results with per-method detail.

    The response includes a `coverageMeasurementUri` field. Pass that URI to
    `abapunit_coverage_query` to retrieve per-class and per-method coverage
    percentages for the same test run."""
    return call_abapunit_run(systemId, objectUris, withCoverage)


@mcp.tool()
def abapunit_coverage_query(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the coverage measurements were collected."),
    measurementUri: str = Field(..., description="Coverage measurement URI returned by abapunit_run in the coverageMeasurementUri field."),
    objectUris: list[str] = Field(..., description="List of ADT repository object URIs to include in the coverage query. Should match the objects passed to abapunit_run.")
) -> AbapUnitCoverageQueryResponse:
    """Query coverage summary (statement, branch, procedure percentages) per class and method for a completed ABAP Unit test run.

    Requires the `coverageMeasurementUri` from `abapunit_run`.

    The response includes a `statementsRequestPaths` list. Pass that list directly
    to `abapunit_coverage_statements` to obtain statement-level (line-by-line)
    coverage detail for each method."""
    return call_abapunit_coverage_query(systemId, measurementUri, objectUris)


@mcp.tool()
def abapunit_coverage_statements(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the coverage measurements were collected."),
    statementsRequestPaths: list[str] = Field(..., description="List of statement request paths returned by abapunit_coverage_query in the statementsRequestPaths field. Each path identifies one method's statement-level coverage data.")
) -> AbapUnitCoverageStatementsResponse:
    """Fetch statement-level (line-by-line) coverage detail for one or more ABAP methods via a bulk request.

    Requires the `statementsRequestPaths` list returned by `abapunit_coverage_query`.

    Returns per-method statement execution counts and branch coverage data,
    allowing precise identification of which lines were not executed during tests."""
    return call_abapunit_coverage_statements(systemId, statementsRequestPaths)
# endregion


def _normalize_tool_mode(mode: str | None = None) -> str:
    """Return the configured MCP tool exposure mode."""
    normalized_mode = str(mode or os.getenv(TOOL_MODE_ENV_VAR, TOOL_MODE_FULL)).strip().lower()
    if normalized_mode not in {TOOL_MODE_FULL, TOOL_MODE_COMPACT}:
        raise ValueError(
            f"{TOOL_MODE_ENV_VAR} must be '{TOOL_MODE_FULL}' or '{TOOL_MODE_COMPACT}', "
            f"got '{normalized_mode}'."
        )
    return normalized_mode


def _capability_category(tool_name: str) -> str:
    """Infer a compact category from an existing ABAP tool name."""
    parts = tool_name.split("_")
    if len(parts) >= 2 and parts[0] in {"source", "ddic", "sap"}:
        return f"{parts[0]}.{parts[1]}"
    if len(parts) >= 2 and parts[0] in {"info"}:
        return "info_repository"
    if len(parts) >= 2 and parts[0] in {"dataelement"}:
        return "ddic.dataelement"
    return parts[0] if parts else "general"


def _brief_tool_description(description: str | None) -> str:
    """Return a short first-line summary for the capability list."""
    text = " ".join(str(description or "").strip().split())
    if not text:
        return ""
    first_sentence_index = text.find(". ")
    if first_sentence_index >= 0:
        text = text[:first_sentence_index + 1]
    return text[:240].rstrip()


def _tool_spec(tool: Any) -> dict[str, Any]:
    """Return the public capability specification for one captured FastMCP tool."""
    annotations = getattr(tool, "annotations", None)
    if hasattr(annotations, "model_dump"):
        annotations = annotations.model_dump(exclude_none=True)
    return {
        "name": tool.name,
        "title": getattr(tool, "title", None),
        "category": _capability_category(tool.name),
        "description": getattr(tool, "description", None) or "",
        "inputSchema": getattr(tool, "parameters", None) or {"type": "object", "properties": {}},
        "outputSchema": getattr(tool, "output_schema", None),
        "annotations": annotations,
    }


def _capability_list_item(tool: Any) -> dict[str, str]:
    """Return the lightweight row exposed by abap_list_capabilities."""
    return {
        "name": tool.name,
        "category": _capability_category(tool.name),
        "description": _brief_tool_description(getattr(tool, "description", None)),
    }


def _remove_public_tool(tool_name: str) -> None:
    """Remove one tool from public exposure using the current FastMCP provider API."""
    local_provider = getattr(mcp, "local_provider", None)
    if local_provider is not None and hasattr(local_provider, "remove_tool"):
        local_provider.remove_tool(tool_name)
        return
    mcp.remove_tool(tool_name)


async def _ensure_compact_capabilities_registered() -> None:
    """Expose only the compact dispatcher tools while retaining the real tools internally."""
    public_tools = await mcp.list_tools()
    real_tools = [tool for tool in public_tools if tool.name not in COMPACT_TOOL_NAMES]

    if real_tools:
        CAPABILITY_TOOLS.clear()
        CAPABILITY_TOOLS.update({tool.name: tool for tool in real_tools})
        for tool in real_tools:
            _remove_public_tool(tool.name)

    public_tool_names = {tool.name for tool in await mcp.list_tools()}
    if "abap_list_capabilities" not in public_tool_names:
        mcp.add_tool(abap_list_capabilities)
    if "abap_get_capability_spec" not in public_tool_names:
        mcp.add_tool(abap_get_capability_spec)
    if "abap_call_capability" not in public_tool_names:
        mcp.add_tool(abap_call_capability)


async def _ensure_full_tools_registered() -> None:
    """Expose the original ABAP tools and hide the compact dispatcher tools."""
    public_tool_names = {tool.name for tool in await mcp.list_tools()}
    for wrapper_name in sorted(COMPACT_DISPATCHER_TOOL_NAMES):
        if wrapper_name in public_tool_names:
            _remove_public_tool(wrapper_name)

    public_tool_names = {tool.name for tool in await mcp.list_tools()}
    for tool in CAPABILITY_TOOLS.values():
        if tool.name not in public_tool_names:
            mcp.add_tool(tool)


async def configure_mcp_tool_mode(mode: str | None = None) -> str:
    """Configure whether the server exposes all tools or the compact capability facade."""
    normalized_mode = _normalize_tool_mode(mode)
    if normalized_mode == TOOL_MODE_COMPACT:
        await _ensure_compact_capabilities_registered()
    else:
        await _ensure_full_tools_registered()
    return normalized_mode


async def abap_list_capabilities(
    category: Annotated[str, Field(description="Optional category filter, e.g. source.program, ddic.table or sap.gui.")] = "",
    query: Annotated[str, Field(description="Optional case-insensitive text filter applied to capability name, category and brief description.")] = "",
) -> dict[str, Any]:
    """List available ABAP capabilities with compact descriptions."""
    normalized_category = str(category or "").strip().lower()
    normalized_query = str(query or "").strip().lower()
    capabilities = []
    for tool in sorted(CAPABILITY_TOOLS.values(), key=lambda item: item.name):
        item = _capability_list_item(tool)
        searchable_text = f"{item['name']} {item['category']} {item['description']}".lower()
        if normalized_category and item["category"].lower() != normalized_category:
            continue
        if normalized_query and normalized_query not in searchable_text:
            continue
        capabilities.append(item)
    return {
        "capabilities": capabilities,
        "totalCount": len(capabilities),
    }


async def abap_get_capability_spec(
    name: Annotated[str, Field(description="Name of the ABAP capability whose full specification should be returned.")],
) -> dict[str, Any]:
    """Return the complete input and output specification for one ABAP capability."""
    capability_name = str(name or "").strip()
    tool = CAPABILITY_TOOLS.get(capability_name)
    if tool is None:
        raise ValueError(f"Unknown ABAP capability: {capability_name}")
    return _tool_spec(tool)


async def abap_call_capability(
    name: Annotated[str, Field(description="Name of the ABAP capability to call.")],
    arguments: Annotated[dict[str, Any], Field(description="Arguments object matching the capability specification returned by abap_get_capability_spec.")],
) -> dict[str, Any]:
    """Call one ABAP capability by name using arguments matching its specification."""
    capability_name = str(name or "").strip()
    tool = CAPABILITY_TOOLS.get(capability_name)
    if tool is None:
        raise ValueError(f"Unknown ABAP capability: {capability_name}")

    result = await tool.run(dict(arguments or {}))
    structured_content = getattr(result, "structured_content", None)
    if structured_content is not None:
        return structured_content

    content = []
    for item in getattr(result, "content", []) or []:
        if hasattr(item, "model_dump"):
            content.append(item.model_dump(exclude_none=True))
        else:
            content.append(item)
    return {"content": content}


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
    args = _parse_args()
    RUN_HOST = args.host
    RUN_PORT = args.port
    RUN_PATH = args.path
    RUN_TRANSPORT = args.transport
    asyncio.run(configure_mcp_tool_mode())
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
