import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

import configuration
from configuration import get_system_config
from generics import ApiResponse

try:
    from playwright.sync_api import sync_playwright, expect, Page, Browser, BrowserContext, Playwright as PlaywrightInstance
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on local environment
    sync_playwright = None
    Page = None
    Browser = None
    BrowserContext = None
    PlaywrightInstance = None
    _PLAYWRIGHT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Global state — one Playwright process, one browser, N pages (one per session)
# ---------------------------------------------------------------------------

_playwright: "PlaywrightInstance | None" = None
_browser: "Browser | None" = None
_CDP_PORT = 9333

@dataclass
class SapWebguiSessionContext:
    """In-memory metadata for one open SAP WebGUI browser session."""

    webguiSessionId: str
    systemId: str
    context: "BrowserContext"
    page: "Page"
    webguiUrl: str = field(default="")
    recording_output_file: Optional[str] = field(default=None)
    recording_process: Optional[subprocess.Popen] = field(default=None)
    recording_stdout_queue: Optional["queue.Queue[str | None]"] = field(default=None)
    recording_diagnostics: list[str] = field(default_factory=list)
    recording_diagnostics_attached: bool = field(default=False)


WEBGUI_SESSIONS: dict[str, SapWebguiSessionContext] = {}   # webguiSessionId -> context


def _get_or_start_browser() -> "Browser":
    """Return the shared Chromium browser, starting Playwright if needed."""
    global _playwright, _browser
    if _browser is not None:
        try:
            if _browser.is_connected():
                return _browser
        except Exception:
            pass
        _browser = None

    if _playwright is None:
        _playwright = sync_playwright().start()

    try:
        _browser = _playwright.chromium.launch(
            headless=False,
            args=[f"--remote-debugging-port={_CDP_PORT}"],
        )
    except Exception:
        _reset_playwright_driver()
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=False,
            args=[f"--remote-debugging-port={_CDP_PORT}"],
        )
    return _browser


def _reset_playwright_driver() -> None:
    """Forget stale Playwright objects so the next call starts a clean driver/browser."""
    global _playwright, _browser
    try:
        if _browser is not None and _browser.is_connected():
            _browser.close()
    except Exception:
        pass
    _browser = None
    try:
        if _playwright is not None:
            _playwright.stop()
    except Exception:
        pass
    _playwright = None


def _sessions_for_system(systemId: str) -> list[SapWebguiSessionContext]:
    normalized = systemId.upper()
    return [ctx for ctx in WEBGUI_SESSIONS.values() if ctx.systemId == normalized]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SapWebguiSessionListItem(BaseModel):
    """Metadata describing one open SAP WebGUI browser session."""

    webguiSessionId: str = Field(..., description="Internal MCP identifier for this WebGUI session. Pass it to sap_webgui_session_close.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with this session.")
    currentUrl: str = Field(..., description="Current URL of the browser page, useful to verify navigation state.")


class SapWebguiSessionListOutput(BaseModel):
    """List of SAP WebGUI browser sessions currently open in the MCP server."""

    sessions: list[SapWebguiSessionListItem] = Field(
        default_factory=list,
        description="Open SAP WebGUI browser sessions."
    )
    totalCount: int = Field(..., description="Number of open SAP WebGUI sessions.")


class SapWebguiSessionListResponse(ApiResponse[SapWebguiSessionListOutput]):
    """Response model for listing open SAP WebGUI sessions."""


class SapWebguiSessionOpenOutput(BaseModel):
    """Metadata returned when a SAP WebGUI browser session is opened and authenticated."""

    webguiSessionId: str = Field(..., description="Internal MCP identifier for the new WebGUI session. Pass it to sap_webgui_session_close when done.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with this session.")
    webguiUrl: str = Field(..., description="SAP WebGUI URL used to open the session.")
    currentUrl: str = Field(..., description="URL after login — differs from webguiUrl once SAP navigates to the main screen.")


class SapWebguiSessionOpenResponse(ApiResponse[SapWebguiSessionOpenOutput]):
    """Response model for opening one SAP WebGUI browser session."""


class SapWebguiSessionCloseOutput(BaseModel):
    """Metadata returned when a SAP WebGUI browser session is closed."""

    webguiSessionId: str = Field(..., description="Internal MCP identifier of the closed session.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with the closed session.")
    alreadyClosed: bool = Field(..., description="True when the browser page was already gone and only the MCP registration had to be removed.")


class SapWebguiSessionCloseResponse(ApiResponse[SapWebguiSessionCloseOutput]):
    """Response model for closing one SAP WebGUI browser session."""


# -- Snapshot ----------------------------------------------------------------

class SapWebguiSnapshotOutput(BaseModel):
    """Accessibility tree of the current SAP WebGUI page."""

    snapshot: str = Field(..., description="Accessibility tree of the current page in ARIA snapshot (YAML) format. Use this to understand what elements are on screen before acting.")


class SapWebguiSnapshotResponse(ApiResponse[SapWebguiSnapshotOutput]):
    """Response model for capturing an accessibility snapshot."""


# -- Screenshot --------------------------------------------------------------

class SapWebguiScreenshotOutput(BaseModel):
    """Screenshot of the current SAP WebGUI page."""

    imageBase64: str = Field(..., description="PNG screenshot encoded as a base64 string.")
    mimeType: str = Field("image/png", description="MIME type of the image.")


class SapWebguiScreenshotResponse(ApiResponse[SapWebguiScreenshotOutput]):
    """Response model for taking a screenshot."""


# -- Generic action (click / type / press_key / navigate) -------------------

class SapWebguiActionOutput(BaseModel):
    """Result of a browser interaction on a SAP WebGUI page."""

    currentUrl: str = Field(..., description="Current browser URL after the action was performed.")


class SapWebguiActionResponse(ApiResponse[SapWebguiActionOutput]):
    """Response model for generic SAP WebGUI browser actions."""


# -- Fill form ---------------------------------------------------------------

class SapWebguiFillFormField(BaseModel):
    """One field to fill inside a SAP WebGUI form."""

    target: str = Field(..., description="CSS selector or Playwright element reference identifying the field.")
    name: str = Field(..., description="Human-readable field name (used only for logging).")
    type: str = Field(..., description="Field type: 'textbox', 'checkbox', 'radio', or 'combobox'.")
    value: str = Field(..., description="Value to set. For checkbox/radio use 'true'/'false'. For combobox use the visible option text.")


class SapWebguiFillFormOutput(BaseModel):
    """Result of a fill-form action on a SAP WebGUI page."""

    currentUrl: str = Field(..., description="Current browser URL after all fields were filled.")
    fieldsFilledCount: int = Field(..., description="Number of fields that were successfully filled.")


class SapWebguiFillFormResponse(ApiResponse[SapWebguiFillFormOutput]):
    """Response model for filling multiple form fields at once."""


# -- Recording ---------------------------------------------------------------

class SapWebguiRecordingStartOutput(BaseModel):
    """Result of starting a Playwright recording session on a SAP WebGUI page."""

    outputFile: str = Field(..., description="Absolute path where Playwright will write the TypeScript script in real time.")


class SapWebguiRecordingStartResponse(ApiResponse[SapWebguiRecordingStartOutput]):
    """Response model for starting a Playwright recording session."""


class SapWebguiRecordingStopOutput(BaseModel):
    """Result of stopping a Playwright recording session on a SAP WebGUI page."""

    outputFile: str = Field(..., description="Absolute path of the generated TypeScript script.")
    script: str = Field(..., description="Full content of the generated Playwright TypeScript script.")
    diagnostics: list[str] = Field(default_factory=list, description="Recorder diagnostics captured during the session.")


class SapWebguiRecordingStopResponse(ApiResponse[SapWebguiRecordingStopOutput]):
    """Response model for stopping a Playwright recording session."""


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def call_sap_webgui_sessions_list() -> SapWebguiSessionListResponse:
    """Return all SAP WebGUI browser sessions currently open in the MCP server."""
    items: list[SapWebguiSessionListItem] = []
    stale_ids: list[str] = []

    for session_id, ctx in list(WEBGUI_SESSIONS.items()):
        try:
            current_url = ctx.page.url
            items.append(SapWebguiSessionListItem(
                webguiSessionId=session_id,
                systemId=ctx.systemId,
                currentUrl=current_url,
            ))
        except Exception:
            stale_ids.append(session_id)

    for session_id in stale_ids:
        WEBGUI_SESSIONS.pop(session_id, None)

    return SapWebguiSessionListResponse.model_validate({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": f"{len(items)} SAP WebGUI session(s) open.",
        "data": SapWebguiSessionListOutput(sessions=items, totalCount=len(items)),
    })


def call_sap_webgui_session_open(systemId: str) -> SapWebguiSessionOpenResponse:
    """Open a Chromium browser, navigate to the SAP WebGUI URL and log in with the configured credentials."""
    if not _PLAYWRIGHT_AVAILABLE:
        return SapWebguiSessionOpenResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            "data": None,
        })

    try:
        system_config = get_system_config(systemId)
    except KeyError as exc:
        return SapWebguiSessionOpenResponse.model_validate({
            "result": False, "httpCode": 404, "httpReason": "Not Found",
            "message": str(exc), "data": None,
        })

    active_recordings = [
        session_id for session_id, ctx in WEBGUI_SESSIONS.items()
        if ctx.recording_output_file
    ]
    if active_recordings:
        return SapWebguiSessionOpenResponse.model_validate({
            "result": False,
            "httpCode": 409,
            "httpReason": "Conflict",
            "message": (
                "Cannot open a new SAP WebGUI session while a Playwright recording is active. "
                "Stop the recording first to avoid recording login credentials from another session."
            ),
            "data": None,
        })

    webgui_url = getattr(system_config, "sap_webgui_url", None) or ""
    if not webgui_url:
        return SapWebguiSessionOpenResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": (
                f"No sap_webgui_url configured for system {system_config.id}. "
                "Add the 'sap_webgui_url' field to this system in the dashboard."
            ),
            "data": None,
        })

    context = None
    try:
        try:
            browser = _get_or_start_browser()
            context = browser.new_context(ignore_https_errors=not system_config.verify_ssl)
            page = context.new_page()
        except Exception:
            _reset_playwright_driver()
            browser = _get_or_start_browser()
            context = browser.new_context(ignore_https_errors=not system_config.verify_ssl)
            page = context.new_page()

        page.goto(webgui_url, wait_until="domcontentloaded", timeout=30_000)

        # SAP WebGUI shells differ between themes/settings. Do not require one
        # exact post-login button; accept any stable main-screen signal.
        try:
            _login_webgui_page(page, system_config)
            _configure_webgui_settings(page)
        except Exception:
            error_text = _extract_login_error(page)
            if error_text:
                if context is not None:
                    context.close()
                reason = error_text or "SAP main screen did not appear after login."
                return SapWebguiSessionOpenResponse.model_validate({
                    "result": False, "httpCode": 401, "httpReason": "Unauthorized",
                    "message": f"SAP WebGUI login failed for system {system_config.id}: {reason}",
                    "data": None,
                })

        session_id = str(uuid.uuid4())
        WEBGUI_SESSIONS[session_id] = SapWebguiSessionContext(
            webguiSessionId=session_id,
            systemId=system_config.id,
            context=context,
            page=page,
            webguiUrl=webgui_url,
        )

        return SapWebguiSessionOpenResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": f"SAP WebGUI session opened successfully for system {system_config.id}.",
            "data": SapWebguiSessionOpenOutput(
                webguiSessionId=session_id,
                systemId=system_config.id,
                webguiUrl=webgui_url,
                currentUrl=page.url,
            ),
        })

    except Exception as exc:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        return SapWebguiSessionOpenResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Unexpected error while opening SAP WebGUI session: {str(exc)}",
            "data": None,
        })


def call_sap_webgui_session_close(webguiSessionId: str) -> SapWebguiSessionCloseResponse:
    """Close one SAP WebGUI browser session and remove it from the MCP server registry."""
    ctx = WEBGUI_SESSIONS.get(webguiSessionId)
    if ctx is None:
        return SapWebguiSessionCloseResponse.model_validate({
            "result": False, "httpCode": 404, "httpReason": "Not Found",
            "message": f"No SAP WebGUI session found with id '{webguiSessionId}'.",
            "data": None,
        })

    already_closed = False
    try:
        if ctx.recording_output_file:
            _disable_playwright_recorder(ctx)
        ctx.context.close()
    except Exception:
        already_closed = True

    WEBGUI_SESSIONS.pop(webguiSessionId, None)

    if not WEBGUI_SESSIONS:
        _reset_playwright_driver()

    return SapWebguiSessionCloseResponse.model_validate({
        "result": True, "httpCode": 200, "httpReason": "OK",
        "message": f"SAP WebGUI session {webguiSessionId} closed for system {ctx.systemId}.",
        "data": SapWebguiSessionCloseOutput(
            webguiSessionId=webguiSessionId,
            systemId=ctx.systemId,
            alreadyClosed=already_closed,
        ),
    })


def call_sap_webgui_snapshot(webguiSessionId: str) -> SapWebguiSnapshotResponse:
    """Capture the accessibility tree of the current SAP WebGUI page."""
    ctx, err = _require_session(webguiSessionId, SapWebguiSnapshotResponse)
    if err:
        return err
    try:
        raw = ctx.page.aria_snapshot()
        return SapWebguiSnapshotResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": "Accessibility snapshot captured.",
            "data": SapWebguiSnapshotOutput(snapshot=raw),
        })
    except Exception as exc:
        return SapWebguiSnapshotResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Failed to capture snapshot: {exc}", "data": None,
        })


def call_sap_webgui_screenshot(webguiSessionId: str, fullPage: bool = False) -> SapWebguiScreenshotResponse:
    """Take a PNG screenshot of the current SAP WebGUI page."""
    ctx, err = _require_session(webguiSessionId, SapWebguiScreenshotResponse)
    if err:
        return err
    try:
        img = ctx.page.screenshot(full_page=fullPage)
        return SapWebguiScreenshotResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": "Screenshot captured.",
            "data": SapWebguiScreenshotOutput(imageBase64=base64.b64encode(img).decode("ascii")),
        })
    except Exception as exc:
        return SapWebguiScreenshotResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Failed to take screenshot: {exc}", "data": None,
        })


def call_sap_webgui_click(
    webguiSessionId: str,
    target: str,
    button: str = "left",
    doubleClick: bool = False,
    modifiers: list[str] | None = None,
) -> SapWebguiActionResponse:
    """Click (or double-click) an element on the current SAP WebGUI page."""
    ctx, err = _require_session(webguiSessionId, SapWebguiActionResponse)
    if err:
        return err
    try:
        locator = ctx.page.locator(target)
        kwargs: dict = {"button": button, "modifiers": modifiers or [], "timeout": 5_000}
        if doubleClick:
            locator.dblclick(**kwargs)
        else:
            locator.click(**kwargs)
        return SapWebguiActionResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": f"{'Double-clicked' if doubleClick else 'Clicked'} '{target}'.",
            "data": SapWebguiActionOutput(currentUrl=ctx.page.url),
        })
    except Exception as exc:
        return SapWebguiActionResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Click failed: {exc}", "data": None,
        })


def call_sap_webgui_type(
    webguiSessionId: str,
    target: str,
    text: str,
    slowly: bool = False,
    submit: bool = False,
) -> SapWebguiActionResponse:
    """Type text into a field on the current SAP WebGUI page."""
    ctx, err = _require_session(webguiSessionId, SapWebguiActionResponse)
    if err:
        return err
    try:
        locator = ctx.page.locator(target)
        if slowly:
            locator.press_sequentially(text, timeout=15_000)
        else:
            locator.fill(text, timeout=5_000)
        if submit:
            ctx.page.keyboard.press("Enter")
        return SapWebguiActionResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": f"Typed into '{target}'" + (" and pressed Enter." if submit else "."),
            "data": SapWebguiActionOutput(currentUrl=ctx.page.url),
        })
    except Exception as exc:
        return SapWebguiActionResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Type failed: {exc}", "data": None,
        })


def call_sap_webgui_press_key(webguiSessionId: str, key: str) -> SapWebguiActionResponse:
    """Press a keyboard key on the current SAP WebGUI page (e.g. Enter, F4, F8, Escape)."""
    ctx, err = _require_session(webguiSessionId, SapWebguiActionResponse)
    if err:
        return err
    try:
        ctx.page.keyboard.press(key)
        return SapWebguiActionResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": f"Key '{key}' pressed.",
            "data": SapWebguiActionOutput(currentUrl=ctx.page.url),
        })
    except Exception as exc:
        return SapWebguiActionResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Key press failed: {exc}", "data": None,
        })


def call_sap_webgui_fill_form(
    webguiSessionId: str,
    fields: list[SapWebguiFillFormField],
) -> SapWebguiFillFormResponse:
    """Fill multiple form fields at once on the current SAP WebGUI page."""
    ctx, err = _require_session(webguiSessionId, SapWebguiFillFormResponse)
    if err:
        return err
    try:
        filled = 0
        for f in fields:
            locator = ctx.page.locator(f.target)
            if f.type == "textbox":
                locator.fill(f.value, timeout=5_000)
            elif f.type in ("checkbox", "radio"):
                if f.value.lower() in ("true", "1", "yes"):
                    locator.check(timeout=5_000)
                else:
                    locator.uncheck(timeout=5_000)
            elif f.type == "combobox":
                locator.select_option(f.value, timeout=5_000)
            filled += 1
        return SapWebguiFillFormResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": f"{filled} field(s) filled.",
            "data": SapWebguiFillFormOutput(currentUrl=ctx.page.url, fieldsFilledCount=filled),
        })
    except Exception as exc:
        return SapWebguiFillFormResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Fill form failed: {exc}", "data": None,
        })


def call_sap_webgui_navigate(webguiSessionId: str, url: str) -> SapWebguiActionResponse:
    """Navigate the SAP WebGUI browser session to a specific URL."""
    ctx, err = _require_session(webguiSessionId, SapWebguiActionResponse)
    if err:
        return err
    if not url:
        return SapWebguiActionResponse.model_validate({
            "result": False, "httpCode": 400, "httpReason": "Bad Request",
            "message": "url is required.", "data": None,
        })
    try:
        ctx.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return SapWebguiActionResponse.model_validate({
            "result": True, "httpCode": 200, "httpReason": "OK",
            "message": f"Navigated to {url}.",
            "data": SapWebguiActionOutput(currentUrl=ctx.page.url),
        })
    except Exception as exc:
        return SapWebguiActionResponse.model_validate({
            "result": False, "httpCode": 500, "httpReason": "Internal Server Error",
            "message": f"Navigation failed: {exc}", "data": None,
        })


def call_sap_webgui_recording_start(
    webguiSessionId: str,
    outputFile: str = "recording.ts",
) -> SapWebguiRecordingStartResponse:
    """Enable Playwright's built-in recorder on an existing SAP WebGUI session, writing TypeScript to a file."""
    ctx, err = _require_session(webguiSessionId, SapWebguiRecordingStartResponse)
    if err:
        return err

    abs_path = os.path.abspath(outputFile)
    if ctx.recording_output_file:
        return SapWebguiRecordingStartResponse.model_validate({
            "result": False,
            "httpCode": 409,
            "httpReason": "Conflict",
            "message": (
                "A recording is already active for this SAP WebGUI session. "
                "Stop it before starting a new one."
            ),
            "data": None,
        })

    try:
        output_dir = os.path.dirname(abs_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8"):
            pass

        ctx.recording_diagnostics.clear()
        _attach_recording_diagnostics(ctx)
        _enable_playwright_recorder(ctx, abs_path)
        ctx.recording_output_file = abs_path
        _capture_recorder_overlay_state(ctx, "start")

        return SapWebguiRecordingStartResponse.model_validate({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": (
                f"Recording started. Perform actions in the browser window. "
                f"Call sap_webgui_recording_stop when done. Output → {abs_path}"
            ),
            "data": SapWebguiRecordingStartOutput(outputFile=abs_path),
        })

    except Exception as exc:
        return SapWebguiRecordingStartResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to start recording: {exc}",
            "data": None,
        })


def call_sap_webgui_recording_stop(webguiSessionId: str) -> SapWebguiRecordingStopResponse:
    """Disable Playwright's recorder and return the generated TypeScript script."""
    ctx, err = _require_session(webguiSessionId, SapWebguiRecordingStopResponse)
    if err:
        return err

    abs_path = ctx.recording_output_file or os.path.abspath("recording.ts")

    try:
        _capture_recorder_overlay_state(ctx, "before-stop")
        _disable_playwright_recorder(ctx)
        time.sleep(0.35)

        ctx.recording_output_file = None

    except Exception as exc:
        return SapWebguiRecordingStopResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to stop recorder: {exc}",
            "data": None,
        })

    if not os.path.exists(abs_path):
        return SapWebguiRecordingStopResponse.model_validate({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": (
                f"Recorder stopped but no output file found at '{abs_path}'. "
                "Either no actions were recorded or the path is incorrect."
            ),
            "data": None,
        })

    try:
        with open(abs_path, encoding="utf-8") as f:
            script = f.read()
        script = _redact_recording_secrets(script)
        with open(abs_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
    except Exception as exc:
        return SapWebguiRecordingStopResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Recorder stopped but could not read output file: {exc}",
            "data": None,
        })

    return SapWebguiRecordingStopResponse.model_validate({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": f"Recording stopped. Script saved to '{abs_path}'.",
        "data": SapWebguiRecordingStopOutput(
            outputFile=abs_path,
            script=script,
            diagnostics=ctx.recording_diagnostics[-100:],
        ),
    })


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _disable_playwright_recorder(ctx: SapWebguiSessionContext) -> None:
    """Disable Playwright's recorder for a WebGUI browser context."""
    if ctx.recording_process is not None:
        _stop_node_recorder(ctx)
        return

    sync_context = ctx.page.context
    sync_context._sync(
        sync_context._impl_obj._channel.send(
            "disableRecorder",
            None,
            {},
        )
    )


def _enable_playwright_recorder(ctx: SapWebguiSessionContext, output_file: str) -> None:
    """Enable Playwright's recorder using the same core parameters as codegen."""
    process = _start_node_recorder(ctx, output_file)
    ctx.recording_process = process
    return


def _enable_python_playwright_recorder(ctx: SapWebguiSessionContext, output_file: str) -> None:
    """Enable Playwright's recorder through the Python protocol channel."""
    system_config = get_system_config(ctx.systemId)
    ignore_https_errors = not bool(getattr(system_config, "verify_ssl", True))
    sync_context = ctx.page.context
    sync_context._sync(
        sync_context._impl_obj._channel.send(
            "enableRecorder",
            None,
            {
                "language": "playwright-test",
                "launchOptions": {},
                "contextOptions": {
                    "ignoreHTTPSErrors": ignore_https_errors,
                },
                "mode": "recording",
                "outputFile": output_file,
                "handleSIGINT": False,
            },
        )
    )


def _playwright_node_package_path() -> str:
    """Return the Node package bundled with the installed Playwright Python package."""
    import playwright

    return str(Path(playwright.__file__).resolve().parent / "driver" / "package")


def _start_node_recorder(ctx: SapWebguiSessionContext, output_file: str) -> subprocess.Popen:
    """Start a Node helper that connects to the Python-launched Chromium over CDP."""
    helper_path = Path(__file__).with_name("playwright_recorder_helper.js")
    system_config = get_system_config(ctx.systemId)
    ignore_https_errors = not bool(getattr(system_config, "verify_ssl", True))
    cmd = [
        "node",
        str(helper_path),
        "--cdp",
        f"http://127.0.0.1:{_CDP_PORT}",
        "--url",
        ctx.page.url,
        "--output",
        output_file,
        "--package",
        _playwright_node_package_path(),
        _playwright_node_package_path(),
        "--ignore-https-errors",
        "true" if ignore_https_errors else "false",
    ]
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parent.parent),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
    )
    deadline = time.time() + 10
    output_lines: list[str] = []
    stdout_queue: "queue.Queue[str | None]" = queue.Queue()

    def read_stdout() -> None:
        try:
            if process.stdout:
                try:
                    for stdout_line in process.stdout:
                        stdout_queue.put(stdout_line)
                except ValueError:
                    pass
        finally:
            stdout_queue.put(None)

    threading.Thread(target=read_stdout, daemon=True).start()
    ctx.recording_stdout_queue = stdout_queue

    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise RuntimeError(f"Node recorder helper exited early with code {process.returncode}: {stdout}{stderr}")
        try:
            line = stdout_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            continue
        if line:
            output_lines.append(line.strip())
            _append_recording_diagnostic(ctx, f"node-recorder: {line.strip()}")
            if line.strip() == "READY":
                return process
    process.terminate()
    ctx.recording_stdout_queue = None
    raise RuntimeError(f"Node recorder helper did not become ready. Output: {' | '.join(output_lines)}")


def _stop_node_recorder(ctx: SapWebguiSessionContext) -> None:
    """Ask the Node recorder helper to disable the recorder and exit."""
    process = ctx.recording_process
    if process is None:
        return
    try:
        if process.poll() is None and process.stdin:
            process.stdin.write("stop\n")
            process.stdin.flush()

        stdout_queue = ctx.recording_stdout_queue
        deadline = time.time() + 5
        while time.time() < deadline:
            if stdout_queue is not None:
                try:
                    line = stdout_queue.get(timeout=0.1)
                except queue.Empty:
                    line = None
                if line:
                    _append_recording_diagnostic(ctx, f"node-recorder: {line.strip()}")
                    if line.strip() == "STOPPED":
                        break
            if process.poll() is not None:
                break

        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=3)
        try:
            if process.stderr:
                for line in process.stderr.read().splitlines():
                    _append_recording_diagnostic(ctx, f"node-recorder-error: {line}")
        except Exception:
            pass
    finally:
        ctx.recording_process = None
        ctx.recording_stdout_queue = None


def _login_webgui_page(page: "Page", system_config) -> None:
    """Log in to SAP WebGUI on a page that may already have the recorder installed."""
    _fill_if_present(page, '[name="sap-client"]', system_config.client)
    _fill_by_role(page, "textbox", "User Required", system_config.user)
    _fill_by_role(page, "textbox", "Password Required", system_config.password)
    _set_language_dropdown(page, system_config.language)

    page.get_by_role("button", name="Log On Emphasized").click(timeout=5_000)


def _configure_webgui_settings(page: "Page") -> None:
    """Configure SAP WebGUI settings."""
    page.get_by_role("button", name="Menu", exact=True).click(timeout=5_000)
    page.get_by_text("Expand menu", exact=True).click(timeout=5_000)
    page.get_by_role("button", name="GUI Actions and Settings", exact=True).click(timeout=5_000)
    page.get_by_text("Settings...", exact=True).click(timeout=5_000)

    page.locator("#wguOptOkHid-Off").click(timeout=5_000)
    page.locator("#wguOptIcnTb-Off").click(timeout=5_000)

    page.get_by_role("button", name="Save Emphasized", exact=True).click(timeout=5_000)


def _attach_recording_diagnostics(ctx: SapWebguiSessionContext) -> None:
    """Attach lightweight page diagnostics while the WebGUI recorder is active."""
    if ctx.recording_diagnostics_attached:
        return

    def append(message: str) -> None:
        _append_recording_diagnostic(ctx, message)

    ctx.page.on("console", lambda msg: append(f"console:{msg.type}: {msg.text}"))
    ctx.page.on("pageerror", lambda exc: append(f"pageerror: {exc}"))
    ctx.page.on("crash", lambda *args: append("page crash"))
    ctx.page.on("close", lambda *args: append("page close"))
    ctx.page.on("framenavigated", lambda frame: _on_recording_frame_navigated(ctx, frame))
    ctx.recording_diagnostics_attached = True


def _on_recording_frame_navigated(ctx: SapWebguiSessionContext, frame) -> None:
    """Record frame navigation while avoiding Playwright sync reentrancy."""
    _append_recording_diagnostic(ctx, f"frame navigated: {frame.url}")


def _append_recording_diagnostic(ctx: SapWebguiSessionContext, message: str) -> None:
    """Keep a bounded in-memory diagnostic log for one WebGUI recording."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    ctx.recording_diagnostics.append(f"{timestamp} {message}")
    if len(ctx.recording_diagnostics) > 200:
        del ctx.recording_diagnostics[: len(ctx.recording_diagnostics) - 200]


def _capture_recorder_overlay_state(ctx: SapWebguiSessionContext, label: str) -> None:
    """Record whether Playwright's recorder overlay is installed in page frames."""
    try:
        states = []
        for frame in ctx.page.frames:
            try:
                state = frame.evaluate(
                    "() => ({"
                    "url: location.href,"
                    "hasRefreshOverlay: typeof window.__pw_refreshOverlay === 'function',"
                    "hasRecorderState: typeof window.__pw_recorderState === 'function',"
                    "hasGlass: !!document.querySelector('x-pw-glass'),"
                    "hasHighlight: !!document.querySelector('x-pw-highlight')"
                    "})"
                )
                states.append(state)
            except Exception as exc:
                states.append({"url": frame.url, "error": str(exc)})
        _append_recording_diagnostic(ctx, f"{label} overlay state: {json.dumps(states, ensure_ascii=False)}")
    except Exception as exc:
        _append_recording_diagnostic(ctx, f"{label} overlay state failed: {exc}")


def _require_session(webguiSessionId: str, response_cls):
    """Return (ctx, None) if the session exists, or (None, 404-response) otherwise."""
    ctx = WEBGUI_SESSIONS.get(webguiSessionId)
    if ctx is None:
        err = response_cls.model_validate({
            "result": False, "httpCode": 404, "httpReason": "Not Found",
            "message": f"No SAP WebGUI session found with id '{webguiSessionId}'.",
            "data": None,
        })
        return None, err
    return ctx, None


def _fill_if_present(page: "Page", selector: str, value: str) -> None:
    """Fill a CSS-selector field only when it resolves to a visible element."""
    try:
        locator = page.locator(selector).first
        if locator.count() > 0 and locator.is_visible(timeout=1_000):
            locator.fill(value, timeout=3_000)
    except Exception:
        pass


def _fill_by_role(page: "Page", role: str, name: str, value: str) -> None:
    """Fill a form field located by ARIA role and accessible name."""
    try:
        page.get_by_role(role, name=name).fill(value, timeout=3_000)
    except Exception:
        pass


def _set_language_dropdown(page: "Page", language: str) -> None:
    """Select the logon language via the SAP WebGUI language dropdown."""
    if not language:
        return
    try:
        page.locator("#sap-language-dropdown-btn").click(timeout=2_000)
        page.get_by_text(language.upper(), exact=True).click(timeout=2_000)
    except Exception:
        # Dropdown may not exist on all ITS versions — not a fatal error.
        pass


def _extract_login_error(page: "Page") -> str:
    """Return a non-empty string if the page shows a SAP login error, empty string otherwise."""
    error_selectors = [
        ".urMsgBarError",
        ".sapMMessageToast",
        "#MESSAGE_TEXT",
    ]
    for selector in error_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible(timeout=500):
                text = locator.inner_text(timeout=1_000).strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def _redact_recording_secrets(script: str) -> str:
    """Remove configured SAP passwords from generated recorder scripts."""
    redacted = script
    for system_config in getattr(configuration, "SYSTEM_CONFIGS", {}).values():
        password = getattr(system_config, "password", None)
        if password:
            redacted = redacted.replace(str(password), "<SAP_PASSWORD>")
    return redacted
