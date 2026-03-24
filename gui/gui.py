import json
import os
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

from pydantic import BaseModel, Field

from configuration import get_system_config
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, ensure_absolute_file_path, write_text_file

try:
    import pythoncom
    import win32com.client
except ImportError:  # pragma: no cover - depends on local Windows environment
    pythoncom = None
    win32com = None


@dataclass
class SapGuiSessionContext:
    """In-memory metadata used to reconnect to one SAP GUI scripting session."""

    guiSessionId: str
    systemId: str
    connectionName: str
    nativeSessionId: str


@dataclass
class SapGuiRecordingContext:
    """Background recorder lifecycle for one SAP GUI session."""

    guiSessionId: str
    nativeSessionId: str
    folderPath: str
    sapFileName: str
    stopEvent: threading.Event = field(default_factory=threading.Event)
    startedEvent: threading.Event = field(default_factory=threading.Event)
    finishedEvent: threading.Event = field(default_factory=threading.Event)
    errorMessage: str | None = None
    worker: threading.Thread | None = None
    captures: list[dict] = field(default_factory=list)
    listenerProcess: subprocess.Popen | None = None
    listenerStopFilePath: str = ""
    listenerReadyFilePath: str = ""
    listenerLogFilePath: str = ""
    listenerEventsFilePath: str = ""


class SapGuiSessionOpenOutput(BaseModel):
    """Metadata returned when one SAP GUI session is opened."""

    guiSessionId: str = Field(..., description="Internal identifier of the opened SAP GUI scripting session.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with the GUI session.")
    connectionName: str = Field(..., description="SAP Logon entry name used or matched for the GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    client: str = Field(..., description="SAP client used by the GUI session.")
    user: str = Field(..., description="SAP user used by the GUI session.")
    language: str = Field(..., description="SAP logon language used for the GUI session when available.")
    attachedToExistingSession: bool = Field(..., description="Always false. Reserved for compatibility with earlier versions of the tool.")


class SapGuiSessionOpenResponse(ApiResponse[SapGuiSessionOpenOutput]):
    """Response model for opening one SAP GUI scripting session."""


class SapGuiSessionCloseOutput(BaseModel):
    """Metadata returned when one SAP GUI session is closed or released."""

    guiSessionId: str = Field(..., description="Internal identifier of the SAP GUI scripting session that was closed or released.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with the GUI session.")
    connectionName: str = Field(..., description="SAP Logon entry name used by the GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    alreadyClosed: bool = Field(..., description="Whether the native SAP GUI session was already gone and only the MCP registration had to be removed.")


class SapGuiSessionCloseResponse(ApiResponse[SapGuiSessionCloseOutput]):
    """Response model for closing one SAP GUI scripting session."""


class SapGuiSessionListItem(BaseModel):
    """Metadata describing one SAP GUI scripting session registered in the MCP server."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the registered SAP GUI scripting session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with the registered GUI session.")
    connectionName: str = Field(..., description="SAP Logon connection name configured for the registered GUI session.")


class SapGuiSessionListOutput(BaseModel):
    """List of SAP GUI scripting sessions currently registered in the MCP server."""

    sessions: list[SapGuiSessionListItem] = Field(default_factory=list, description="SAP GUI scripting sessions currently registered in the MCP server.")
    totalCount: int = Field(..., description="Number of SAP GUI scripting sessions currently registered in the MCP server.")


class SapGuiSessionListResponse(ApiResponse[SapGuiSessionListOutput]):
    """Response model for listing SAP GUI scripting sessions registered in the MCP server."""


class SapGuiSessionScreenshotOutput(BaseModel):
    """Metadata returned when one SAP GUI screenshot is written to a local file."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the SAP GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    filePath: str = Field(..., description="Absolute local file path where the screenshot was written.")
    imageFormat: str = Field(..., description="Image format written by SAP GUI, typically bmp.")
    sizeBytes: int = Field(..., description="Number of bytes written to the screenshot file.")
    windowTitle: str = Field(..., description="Title of the captured main window when available.")


class SapGuiSessionScreenshotResponse(ApiResponse[SapGuiSessionScreenshotOutput]):
    """Response model for writing one SAP GUI screenshot to a local file."""


class SapGuiControlInfo(BaseModel):
    """Metadata describing one SAP GUI control discovered by inspection."""

    id: str = Field(..., description="Full SAP GUI scripting id of the control.")
    type: str = Field("", description="SAP GUI scripting control type.")
    name: str = Field("", description="Control name when available.")
    text: str = Field("", description="Visible text or value when available.")
    tooltip: str = Field("", description="Tooltip text when available.")
    changeable: bool | None = Field(None, description="Whether the control appears editable when this information is available.")
    visible: bool | None = Field(None, description="Whether the control is visible when this information is available.")
    childCount: int = Field(..., description="Number of direct child controls.")
    children: list["SapGuiControlInfo"] = Field(default_factory=list, description="Child controls discovered below this control.")


class SapGuiSessionInspectOutput(BaseModel):
    """Structured snapshot of one SAP GUI session and its visible control tree."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the SAP GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    systemId: str = Field(..., description="Configured SAP system identifier associated with the GUI session.")
    connectionName: str = Field(..., description="SAP Logon connection name configured for the GUI session.")
    windowTitle: str = Field("", description="Current main window title when available.")
    transaction: str = Field("", description="Current transaction code when available.")
    program: str = Field("", description="Current ABAP program name when available.")
    screenNumber: str = Field("", description="Current dynpro screen number when available.")
    controls: list[SapGuiControlInfo] = Field(default_factory=list, description="Root controls discovered in the SAP GUI session.")


class SapGuiSessionInspectResponse(ApiResponse[SapGuiSessionInspectOutput]):
    """Response model for inspecting one SAP GUI session."""


class SapGuiSessionAction(BaseModel):
    """One SAP GUI action to execute inside a batch."""

    actionType: str = Field(..., description="Action to execute. Supported values are sendVKey, setText, press, select, doubleClick, and setFocus.")
    controlId: str = Field("", description="SAP GUI scripting control id to target. Required for every action except sendVKey.")
    value: str = Field("", description="Text value to write when actionType is setText.")
    vkey: int | None = Field(None, description="Virtual key code to send when actionType is sendVKey.")


class SapGuiSessionActionsRequest(BaseModel):
    """One or more SAP GUI actions to execute sequentially against a registered session."""

    actions: list[SapGuiSessionAction] = Field(..., description="Ordered SAP GUI actions to execute. Use a single-item list for simple interactions or multiple items to fill a screen before continuing.")
    waitForCompletion: bool = Field(True, description="When true, wait until SAP GUI finishes reacting to the full batch before returning.")
    timeoutSeconds: int = Field(1800, description="Maximum number of seconds to wait for SAP GUI to finish the full batch. Use larger values for long-running SAP operations.")


class SapGuiVisibleMessage(BaseModel):
    """Current visible SAP message information gathered from the status bar or an open popup."""

    source: str = Field("", description="Where the visible message was found, for example statusBar or popup.")
    text: str = Field("", description="Most relevant visible SAP message text that could be read.")
    type: str = Field("", description="SAP message type when available, for example S, W, E, A, or I.")
    statusBarText: str = Field("", description="Current text shown in the main SAP status bar when available.")
    statusBarType: str = Field("", description="Current SAP status bar message type when available.")
    popupTitle: str = Field("", description="Title of the active popup window when one is visible.")
    popupText: str = Field("", description="Visible text collected from the active popup window when one is visible.")
    popupWindowId: str = Field("", description="SAP GUI scripting id of the active popup window when one is visible.")


class SapGuiSessionReadMessageOutput(BaseModel):
    """Visible SAP message and session context for one registered GUI session."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the SAP GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    windowTitle: str = Field("", description="Current main window title when available.")
    transaction: str = Field("", description="Current transaction code when available.")
    program: str = Field("", description="Current ABAP program name when available.")
    screenNumber: str = Field("", description="Current dynpro screen number when available.")
    message: SapGuiVisibleMessage = Field(default_factory=SapGuiVisibleMessage, description="Most relevant visible SAP message information currently available in the session.")


class SapGuiSessionReadMessageResponse(ApiResponse[SapGuiSessionReadMessageOutput]):
    """Response model for reading the visible SAP message of one session."""


class SapGuiExecutedAction(BaseModel):
    """One SAP GUI action that was executed inside a batch."""

    actionType: str = Field(..., description="Normalized SAP GUI action name that was executed.")
    controlId: str = Field("", description="SAP GUI scripting control id targeted by the action when applicable.")


class SapGuiSessionActionsOutput(BaseModel):
    """Metadata returned after executing one or more SAP GUI session actions."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the SAP GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    actionsExecuted: list[SapGuiExecutedAction] = Field(default_factory=list, description="Ordered SAP GUI actions that were executed successfully.")
    windowTitle: str = Field("", description="Current main window title after the action when available.")
    transaction: str = Field("", description="Current transaction code after the action when available.")
    program: str = Field("", description="Current ABAP program name after the action when available.")
    screenNumber: str = Field("", description="Current dynpro screen number after the action when available.")
    waitedForCompletion: bool = Field(..., description="Whether the tool waited for SAP GUI to finish reacting to the action before returning.")
    timeoutSeconds: int = Field(..., description="Maximum wait time that was applied to the action.")
    message: SapGuiVisibleMessage = Field(default_factory=SapGuiVisibleMessage, description="Most relevant visible SAP message information after the action completed.")


class SapGuiSessionActionsResponse(ApiResponse[SapGuiSessionActionsOutput]):
    """Response model for executing one or more SAP GUI session actions."""


class SapGuiRecordingStartOutput(BaseModel):
    """Metadata returned when SAP GUI native recording is started."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the SAP GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    folderPath: str = Field(..., description="Absolute local folder path where SAP GUI recording artifacts will be written.")
    recordingFilePath: str = Field(..., description="Absolute local file path where the native SAP GUI recording script will be copied.")


class SapGuiRecordingStartResponse(ApiResponse[SapGuiRecordingStartOutput]):
    """Response model for starting SAP GUI native recording."""


class SapGuiRecordingStopOutput(BaseModel):
    """Metadata returned when SAP GUI native recording is stopped."""

    guiSessionId: str = Field(..., description="Internal MCP guiSessionId of the SAP GUI session.")
    nativeSessionId: str = Field(..., description="Native SAP GUI scripting session id.")
    folderPath: str = Field(..., description="Absolute local folder path where SAP GUI recording artifacts were written.")
    recordingFilePath: str = Field(..., description="Absolute local file path where the native SAP GUI recording script was copied.")
    metadataFilePath: str = Field(..., description="Absolute local file path of the JSON metadata generated for the recording.")
    screenshotCount: int = Field(..., description="Number of screenshots captured during the recording. Zero in native-only recording mode.")
    sizeBytes: int | None = Field(None, description="Size of the native recording file when it exists and can be read.")


class SapGuiRecordingStopResponse(ApiResponse[SapGuiRecordingStopOutput]):
    """Response model for stopping SAP GUI native recording."""


SapGuiControlInfo.update_forward_refs()


GUI_SESSIONS: dict[str, SapGuiSessionContext] = {}
GUI_RECORDINGS: dict[str, SapGuiRecordingContext] = {}


def _get_sap_gui_executable_path() -> str:
    """Resolve the SAP Logon executable path from the environment or common locations."""
    configured_path = os.getenv("SAP_GUI_EXECUTABLE_PATH", "").strip()
    if configured_path:
        if os.path.isfile(configured_path):
            return configured_path
        raise FileNotFoundError(
            f"The SAP GUI executable path configured in SAP_GUI_EXECUTABLE_PATH does not exist: {configured_path}"
        )

    path_candidate = which("saplogon.exe")
    if path_candidate:
        return path_candidate

    common_paths = [
        r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe",
        r"C:\Program Files\SAP\FrontEnd\SAPgui\saplogon.exe",
    ]
    for candidate in common_paths:
        if os.path.isfile(candidate):
            return candidate

    raise FileNotFoundError(
        "SAP Logon executable not found. Add saplogon.exe to PATH or define SAP_GUI_EXECUTABLE_PATH in .env."
    )


def _get_sap_gui_scripts_folder() -> Path:
    """Resolve the SAP GUI local scripts folder used by RecordFile."""
    configured_path = os.getenv("SAP_GUI_SCRIPTS_FOLDER", "").strip()
    if configured_path:
        folder_path = Path(configured_path)
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path

    appdata = os.getenv("APPDATA", "").strip()
    if not appdata:
        raise RuntimeError(
            "APPDATA is not available. Define SAP_GUI_SCRIPTS_FOLDER in .env to point to the SAP GUI Scripts folder."
        )

    folder_path = Path(appdata) / "SAP" / "SAP GUI" / "Scripts"
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def _get_event_listener_script_path() -> Path:
    """Return the VBScript helper used to listen for SAP GUI events."""
    script_path = Path(__file__).resolve().parent / "sap_gui_event_listener.vbs"
    if not script_path.exists():
        raise FileNotFoundError(f"SAP GUI event listener script not found: {script_path}")
    return script_path


def _require_scripting_dependencies() -> None:
    """Ensure the local Python environment supports SAP GUI Scripting through COM."""
    if pythoncom is None or win32com is None:
        raise RuntimeError(
            "SAP GUI scripting requires pywin32. Install the dependency and run this MCP server on Windows."
        )


def _launch_sap_logon() -> None:
    """Start SAP Logon if it is not already running."""
    executable_path = _get_sap_gui_executable_path()
    subprocess.Popen([executable_path])


def _is_sap_logon_running() -> bool:
    """Return whether saplogon.exe is already running on the local machine."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq saplogon.exe"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "saplogon.exe" in result.stdout.lower()
    except Exception:
        return False


def _ensure_sap_logon_running() -> None:
    """Start SAP Logon only when it is not already running."""
    if not _is_sap_logon_running():
        _launch_sap_logon()


def _get_scripting_application(max_wait_seconds: float = 5.0):
    """Get the SAP GUI scripting engine, waiting briefly for SAP Logon to initialize."""
    deadline = time.time() + max_wait_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            sap_gui = win32com.client.GetObject("SAPGUI")
            return sap_gui.GetScriptingEngine
        except Exception as exc:  # pragma: no cover - depends on local COM state
            last_error = exc
            time.sleep(0.35)

    raise RuntimeError(
        "SAP GUI scripting engine is not available. Ensure SAP Logon is installed, running, and SAP GUI Scripting is enabled."
    ) from last_error


def _get_scripting_application_with_retry() -> object:
    """Get the SAP GUI scripting engine with a retry strategy suitable for the first attach."""
    try:
        return _get_scripting_application(max_wait_seconds=2.5)
    except Exception:
        time.sleep(0.4)
        try:
            return _get_scripting_application(max_wait_seconds=2.5)
        except Exception as second_error:
            raise RuntimeError(
                "SAP GUI scripting engine is not available. If SAP Logon is already open, bring it to the foreground once and retry."
            ) from second_error


def _get_connection_session(connection, existing_native_session_ids: set[str] | None = None, max_wait_seconds: float = 10.0):
    """Wait until the opened SAP GUI connection exposes its first session."""
    deadline = time.time() + max_wait_seconds
    last_error: Exception | None = None
    existing_native_session_ids = existing_native_session_ids or set()

    while time.time() < deadline:
        try:
            if connection.Children.Count > 0:
                return connection.Children(0)
        except Exception as exc:  # pragma: no cover - depends on local COM state
            last_error = exc

        try:
            application = _get_scripting_application(max_wait_seconds=0.8)
            for item in _iter_visible_sessions(application):
                native_session_id = item["nativeSessionId"]
                if native_session_id and native_session_id not in existing_native_session_ids:
                    return item["session"]
        except Exception as exc:  # pragma: no cover - depends on local COM state
            last_error = exc
        time.sleep(0.35)

    raise RuntimeError("The SAP GUI connection did not expose a session in time.") from last_error


def _safe_getattr(target, attribute_name: str, default: str = "") -> str:
    """Read one COM attribute defensively and normalize missing values to strings."""
    try:
        value = getattr(target, attribute_name)
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _safe_find_text(session, field_id: str, default: str = "") -> str:
    """Read the text of one SAP GUI control if it exists."""
    try:
        control = session.findById(field_id)
        return str(getattr(control, "text", default) or default)
    except Exception:
        return default


def _safe_get_bool(target, attribute_name: str) -> bool | None:
    """Read one COM boolean attribute defensively."""
    try:
        value = getattr(target, attribute_name)
    except Exception:
        return None

    if value is None:
        return None
    return bool(value)


def _try_fill_logon_field(session, field_id: str, value: str) -> bool:
    """Set one SAP GUI logon field if it exists on the current screen."""
    if not value:
        return False

    try:
        session.findById(field_id).text = value
        return True
    except Exception:
        return False


def _perform_logon_if_needed(session, *, client: str, user: str, password: str, language: str) -> None:
    """Fill the standard SAP logon screen if it is present."""
    filled_any = False
    filled_any |= _try_fill_logon_field(session, "wnd[0]/usr/txtRSYST-MANDT", client)
    filled_any |= _try_fill_logon_field(session, "wnd[0]/usr/txtRSYST-BNAME", user)
    filled_any |= _try_fill_logon_field(session, "wnd[0]/usr/pwdRSYST-BCODE", password)
    filled_any |= _try_fill_logon_field(session, "wnd[0]/usr/txtRSYST-LANGU", language)

    if filled_any:
        session.findById("wnd[0]").sendVKey(0)


def _collect_radiobuttons(container) -> list[object]:
    """Collect radio buttons recursively from one SAP GUI container."""
    radio_buttons: list[object] = []
    try:
        child_count = int(container.Children.Count)
    except Exception:
        return radio_buttons

    for child_index in range(child_count):
        try:
            child = container.Children(child_index)
        except Exception:
            continue

        child_type = _safe_getattr(child, "Type").lower()
        if "radiobutton" in child_type:
            radio_buttons.append(child)

        radio_buttons.extend(_collect_radiobuttons(child))

    return radio_buttons


def _select_radiobutton_by_text(container, expected_fragments: list[str]) -> bool:
    """Select the first radio button whose text contains one of the expected fragments."""
    for radio_button in _collect_radiobuttons(container):
        child_text = _safe_getattr(radio_button, "Text").strip().lower()
        if any(fragment in child_text for fragment in expected_fragments):
            try:
                radio_button.select()
                return True
            except Exception:
                try:
                    radio_button.selected = True
                    return True
                except Exception:
                    pass

    return False


def _select_radiobutton_by_index(container, index: int) -> bool:
    """Select one radio button by its visible order inside the popup."""
    radio_buttons = _collect_radiobuttons(container)
    if index < 0 or index >= len(radio_buttons):
        return False

    radio_button = radio_buttons[index]
    try:
        radio_button.select()
        return True
    except Exception:
        try:
            radio_button.selected = True
            return True
        except Exception:
            return False


def _press_primary_button(window) -> bool:
    """Press the first toolbar pushbutton of a popup window."""
    for toolbar_id in ("wnd[1]/tbar[0]/btn[0]", "wnd[1]/tbar[0]/btn[11]"):
        try:
            window.findById(toolbar_id).press()
            return True
        except Exception:
            continue
    return False


def _handle_multiple_logon_popup(session, max_wait_seconds: float = 5.0) -> None:
    """Handle the SAP GUI popup that asks how to proceed when other sessions already exist."""
    deadline = time.time() + max_wait_seconds
    expected_fragments = [
        "without ending",
        "ohne beenden",
        "sin finalizar",
        "sense finalitzar",
        "continue this logon",
        "continue logon",
        "without terminating",
        "ohne die anderen",
    ]

    while time.time() < deadline:
        try:
            popup = session.findById("wnd[1]")
        except Exception:
            return

        if _select_radiobutton_by_text(popup, expected_fragments):
            if _press_primary_button(popup):
                return

        # In the common multi-logon popup, the middle option is the desired one:
        # continue this logon and keep the existing sessions open.
        if _select_radiobutton_by_index(popup, 1):
            if _press_primary_button(popup):
                return

        try:
            popup.sendVKey(0)
            return
        except Exception:
            time.sleep(0.3)


def _read_connection_name(connection) -> str:
    """Return the best available display name for one SAP GUI connection."""
    return (
        _safe_getattr(connection, "Description")
        or _safe_getattr(connection, "Name")
        or _safe_getattr(connection, "ConnectionString")
        or "Unknown Connection"
    )


def _read_window_title(session) -> str:
    """Return the title of the current main window if available."""
    try:
        return str(session.findById("wnd[0]").text or "")
    except Exception:
        return ""


def _collect_visible_texts(control, *, max_depth: int = 8, current_depth: int = 0) -> list[str]:
    """Collect visible non-empty text fragments from one control tree."""
    fragments: list[str] = []

    for attribute_name in ("text", "Text", "tooltip", "Tooltip"):
        try:
            value = getattr(control, attribute_name)
            if value is not None:
                text_value = str(value).strip()
                if text_value:
                    fragments.append(text_value)
        except Exception:
            continue

    if current_depth >= max_depth:
        return fragments

    try:
        child_count = int(control.Children.Count)
    except Exception:
        return fragments

    for child_index in range(child_count):
        try:
            child = control.Children(child_index)
        except Exception:
            continue
        fragments.extend(_collect_visible_texts(child, max_depth=max_depth, current_depth=current_depth + 1))

    return fragments


def _deduplicate_texts(values: list[str]) -> list[str]:
    """Preserve order while removing empty or repeated text fragments."""
    seen: set[str] = set()
    result: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _read_visible_message(session) -> SapGuiVisibleMessage:
    """Read the most relevant currently visible SAP message from the status bar or an open popup."""
    status_bar_text = _safe_find_text(session, "wnd[0]/sbar", "")
    status_bar_type = ""
    try:
        status_bar_type = _safe_getattr(session.findById("wnd[0]/sbar"), "MessageType")
    except Exception:
        status_bar_type = ""

    popup_title = ""
    popup_text = ""
    popup_window_id = ""
    try:
        popup = session.findById("wnd[1]")
        popup_window_id = _safe_getattr(popup, "Id")
        popup_title = _safe_getattr(popup, "Text")
        popup_fragments = _deduplicate_texts(_collect_visible_texts(popup))
        popup_text = "\n".join(fragment for fragment in popup_fragments if fragment != popup_title)
    except Exception:
        popup_title = ""
        popup_text = ""
        popup_window_id = ""

    if popup_text or popup_title:
        return SapGuiVisibleMessage(
            source="popup",
            text=popup_text or popup_title,
            type=status_bar_type,
            statusBarText=status_bar_text,
            statusBarType=status_bar_type,
            popupTitle=popup_title,
            popupText=popup_text,
            popupWindowId=popup_window_id,
        )

    return SapGuiVisibleMessage(
        source="statusBar" if status_bar_text else "",
        text=status_bar_text,
        type=status_bar_type,
        statusBarText=status_bar_text,
        statusBarType=status_bar_type,
        popupTitle="",
        popupText="",
        popupWindowId="",
    )


def _iter_visible_sessions(application) -> list[dict]:
    """Enumerate the SAP GUI sessions currently visible to the scripting engine."""
    visible_sessions: list[dict] = []

    for connection_index in range(application.Children.Count):
        connection = application.Children(connection_index)
        connection_name = _read_connection_name(connection)

        for session_index in range(connection.Children.Count):
            session = connection.Children(session_index)
            info = getattr(session, "Info", None)
            native_session_id = _safe_getattr(session, "Id")
            visible_sessions.append({
                "connection": connection,
                "session": session,
                "nativeSessionId": native_session_id,
                "connectionName": connection_name,
                "systemName": _safe_getattr(info, "SystemName"),
                "client": _safe_getattr(info, "Client"),
                "user": _safe_getattr(info, "User"),
                "transaction": _safe_getattr(info, "Transaction"),
                "program": _safe_getattr(info, "Program"),
                "screenNumber": _safe_getattr(info, "ScreenNumber"),
                "language": _safe_find_text(session, "wnd[0]/usr/txtRSYST-LANGU", _safe_getattr(info, "Language")),
                "windowTitle": _read_window_title(session),
            })

    return visible_sessions


def _normalize_registered_sessions() -> None:
    """Remove MCP registrations whose native SAP GUI session no longer exists."""
    if pythoncom is None or win32com is None:
        return

    try:
        pythoncom.CoInitialize()
        application = _get_scripting_application(max_wait_seconds=2.0)
        visible_native_ids = {
            item["nativeSessionId"]
            for item in _iter_visible_sessions(application)
            if item["nativeSessionId"]
        }
    except Exception:
        return
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()

    stale_ids = [
        gui_session_id
        for gui_session_id, context in GUI_SESSIONS.items()
        if context.nativeSessionId not in visible_native_ids
    ]
    for gui_session_id in stale_ids:
        GUI_SESSIONS.pop(gui_session_id, None)


def _find_context_by_native_session_id(native_session_id: str) -> SapGuiSessionContext | None:
    """Return the registered MCP session context for one native SAP GUI session id."""
    for context in GUI_SESSIONS.values():
        if context.nativeSessionId == native_session_id:
            return context
    return None


def _register_session(system_id: str, connection_name: str, native_session_id: str) -> SapGuiSessionContext:
    """Create or reuse one MCP registration for a native SAP GUI session."""
    existing_context = _find_context_by_native_session_id(native_session_id)
    if existing_context is not None:
        return existing_context

    gui_session_id = f"sapgui-{uuid.uuid4().hex[:12]}"
    context = SapGuiSessionContext(
        guiSessionId=gui_session_id,
        systemId=system_id,
        connectionName=connection_name,
        nativeSessionId=native_session_id,
    )
    GUI_SESSIONS[gui_session_id] = context
    return context


def _find_registered_context(gui_session_id: str) -> SapGuiSessionContext:
    """Return one registered SAP GUI session or raise a clear error."""
    _normalize_registered_sessions()
    context = GUI_SESSIONS.get(gui_session_id)
    if context is None:
        raise KeyError(f"The SAP GUI session '{gui_session_id}' does not exist or has already been closed.")
    return context


def _find_visible_session_by_native_id(application, native_session_id: str) -> dict | None:
    """Return one currently visible SAP GUI session that matches a native session id."""
    for item in _iter_visible_sessions(application):
        if item["nativeSessionId"] == native_session_id:
            return item
    return None


def _get_live_session_for_gui_session_id(gui_session_id: str) -> tuple[SapGuiSessionContext, dict]:
    """Reconnect one registered guiSessionId to the live SAP GUI session."""
    context = _find_registered_context(gui_session_id)
    application = _get_scripting_application(max_wait_seconds=2.0)
    visible_session = _find_visible_session_by_native_id(application, context.nativeSessionId)
    if visible_session is None:
        GUI_SESSIONS.pop(gui_session_id, None)
        raise KeyError(f"The SAP GUI session '{gui_session_id}' is no longer open.")
    return context, visible_session


def _read_session_state(session) -> tuple[bool | None, str, str, str, str, str, str]:
    """Read a small session state snapshot useful for wait conditions."""
    info = getattr(session, "Info", None)
    busy = _safe_get_bool(session, "Busy")
    message = _read_visible_message(session)
    return (
        busy,
        _safe_getattr(info, "Transaction"),
        _safe_getattr(info, "Program"),
        _safe_getattr(info, "ScreenNumber"),
        _read_window_title(session),
        message.text,
        message.popupWindowId,
    )


def _wait_for_session_stable(
    session,
    *,
    timeout_seconds: float = 1800.0,
    poll_interval_seconds: float = 0.2,
    stable_reads_required: int = 3,
) -> None:
    """Wait until the SAP GUI session is no longer busy and the visible state becomes stable."""
    if timeout_seconds <= 0:
        return

    deadline = time.time() + timeout_seconds
    stable_reads = 0
    previous_state: tuple[bool | None, str, str, str, str, str, str] | None = None

    while time.time() < deadline:
        current_state = _read_session_state(session)
        busy = current_state[0]

        if busy is True:
            stable_reads = 0
            previous_state = current_state
            time.sleep(poll_interval_seconds)
            continue

        if previous_state is not None and current_state == previous_state:
            stable_reads += 1
            if stable_reads >= max(1, stable_reads_required):
                return
        else:
            stable_reads = 0

        previous_state = current_state
        time.sleep(poll_interval_seconds)

    raise TimeoutError(f"SAP GUI action did not finish within {int(timeout_seconds)} seconds.")


def _build_control_tree(control, *, max_depth: int, current_depth: int = 0) -> SapGuiControlInfo:
    """Recursively serialize one SAP GUI control tree."""
    child_count = 0
    children: list[SapGuiControlInfo] = []

    try:
        child_count = int(control.Children.Count)
    except Exception:
        child_count = 0

    if current_depth < max_depth:
        for child_index in range(child_count):
            try:
                child = control.Children(child_index)
                children.append(_build_control_tree(child, max_depth=max_depth, current_depth=current_depth + 1))
            except Exception:
                continue

    return SapGuiControlInfo(
        id=_safe_getattr(control, "Id"),
        type=_safe_getattr(control, "Type"),
        name=_safe_getattr(control, "Name"),
        text=_safe_getattr(control, "Text"),
        tooltip=_safe_getattr(control, "Tooltip"),
        changeable=_safe_get_bool(control, "Changeable"),
        visible=_safe_get_bool(control, "Visible"),
        childCount=child_count,
        children=children,
    )


def _find_control(session, control_id: str):
    """Return one SAP GUI control by id or raise a clear error."""
    if not control_id.strip():
        raise ValueError("controlId is required for this SAP GUI action.")

    try:
        return session.findById(control_id)
    except Exception as exc:
        raise ValueError(f"The SAP GUI control '{control_id}' was not found in the current session.") from exc


def _execute_action(session, request: SapGuiSessionAction) -> str:
    """Execute one supported SAP GUI action and return the normalized action name."""
    action_type = request.actionType.strip()
    normalized_action = action_type.lower()

    if normalized_action == "sendvkey":
        if request.vkey is None:
            raise ValueError("vkey is required when actionType is sendVKey.")
        session.findById("wnd[0]").sendVKey(int(request.vkey))
        return "sendVKey"

    control = _find_control(session, request.controlId)

    if normalized_action == "settext":
        control.text = request.value
        return "setText"
    if normalized_action == "press":
        control.press()
        return "press"
    if normalized_action == "select":
        try:
            control.select()
        except Exception:
            control.selected = True
        return "select"
    if normalized_action == "doubleclick":
        control.doubleClick()
        return "doubleClick"
    if normalized_action == "setfocus":
        control.setFocus()
        return "setFocus"

    raise ValueError(
        "Unsupported SAP GUI actionType. Supported values are sendVKey, setText, press, select, doubleClick, and setFocus."
    )


def _set_session_recording(session, enabled: bool) -> None:
    """Enable or disable SAP GUI native recording on one session."""
    try:
        session.Record = enabled
        return
    except Exception:
        pass

    try:
        session.record = enabled
        return
    except Exception as exc:
        raise RuntimeError("Failed to change SAP GUI native recording state.") from exc


def _get_recording_output_paths(recording_context: SapGuiRecordingContext) -> tuple[Path, Path, Path]:
    """Return the target paths for the main recording file, metadata, and a reserved screenshots folder."""
    folder_path = Path(recording_context.folderPath)
    recording_file_path = folder_path / "recording.vbs"
    metadata_file_path = folder_path / "metadata.json"
    screenshots_folder = folder_path / "screenshots"
    return recording_file_path, metadata_file_path, screenshots_folder


def _get_recording_logs_folder(recording_context: SapGuiRecordingContext) -> Path:
    """Return the folder that stores recorder logs."""
    logs_folder = Path(recording_context.folderPath) / "logs"
    logs_folder.mkdir(parents=True, exist_ok=True)
    return logs_folder


def _get_recording_temp_folder(recording_context: SapGuiRecordingContext) -> Path:
    """Return the temporary working folder used while building the final recording artifacts."""
    temp_folder = Path(recording_context.folderPath) / ".tmp"
    temp_folder.mkdir(parents=True, exist_ok=True)
    return temp_folder


def _get_recording_listener_paths(recording_context: SapGuiRecordingContext) -> tuple[Path, Path, Path, Path, Path]:
    """Return the target paths used by the SAP GUI event listener helper."""
    folder_path = Path(recording_context.folderPath)
    temp_folder = _get_recording_temp_folder(recording_context)
    logs_folder = _get_recording_logs_folder(recording_context)
    return (
        temp_folder / "events.jsonl",
        logs_folder / "listener.log",
        temp_folder / "listener.ready",
        temp_folder / "listener.stop",
        temp_folder / "raw_screenshots",
    )


def _get_recording_error_log_path(recording_context: SapGuiRecordingContext) -> Path:
    """Return the path of the recorder error log file."""
    return _get_recording_logs_folder(recording_context) / "errors.log"


def _append_recording_error(recording_context: SapGuiRecordingContext, message: str) -> None:
    """Append one error line to the recorder error log."""
    error_log_path = _get_recording_error_log_path(recording_context)
    error_log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    error_log_path.write_text(
        (
            error_log_path.read_text(encoding="utf-8")
            if error_log_path.exists()
            else ""
        ) + f"[{timestamp}] {message}\n",
        encoding="utf-8",
    )


def _append_recording_exception(recording_context: SapGuiRecordingContext, context_message: str, exc: Exception) -> None:
    """Append one detailed exception block to the recorder error log."""
    _append_recording_error(
        recording_context,
        "\n".join([
            f"{context_message}: {repr(exc)}",
            traceback.format_exc().rstrip(),
        ]),
    )


def _save_metadata(recording_context: SapGuiRecordingContext) -> None:
    """Write the current recording metadata to metadata.json."""
    _, metadata_file_path, _ = _get_recording_output_paths(recording_context)
    listener_log_path = _get_recording_logs_folder(recording_context) / "listener.log"
    error_log_path = _get_recording_logs_folder(recording_context) / "errors.log"
    metadata_file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "guiSessionId": recording_context.guiSessionId,
        "nativeSessionId": recording_context.nativeSessionId,
        "recordingFile": "recording.vbs",
        "logsFolder": "logs",
        "listenerLogFile": str(Path("logs") / listener_log_path.name),
        "errorLogFile": str(Path("logs") / error_log_path.name),
        "screenshotsFolder": "screenshots",
        "screens": [],
        "transitions": [],
        "captures": recording_context.captures,
    }
    metadata_file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_recording_context(gui_session_id: str) -> SapGuiRecordingContext:
    """Return one active recording context or raise a clear error."""
    recording_context = GUI_RECORDINGS.get(gui_session_id)
    if recording_context is None:
        raise ValueError("No SAP GUI native recording is currently registered for this session.")
    return recording_context


def _recording_worker(recording_context: SapGuiRecordingContext) -> None:
    """Keep SAP GUI native recording alive in the background until stop is requested."""
    try:
        _require_scripting_dependencies()
        _append_recording_error(recording_context, "Recording worker starting.")
        pythoncom.CoInitialize()
        _append_recording_error(recording_context, "COM initialized.")
        recording_file_path, _, _ = _get_recording_output_paths(recording_context)
        recording_file_path.parent.mkdir(parents=True, exist_ok=True)
        _append_recording_error(recording_context, f"Output prepared recordingFile={recording_file_path}.")
        application = _get_scripting_application(max_wait_seconds=3.0)
        _append_recording_error(recording_context, "SAP GUI scripting application acquired.")
        visible_session = _find_visible_session_by_native_id(application, recording_context.nativeSessionId)
        if visible_session is None:
            raise RuntimeError("The SAP GUI session is no longer open.")

        session = visible_session["session"]
        _append_recording_error(
            recording_context,
            f"Live session found nativeSessionId={recording_context.nativeSessionId}.",
        )
        session.RecordFile = recording_context.sapFileName
        _append_recording_error(
            recording_context,
            f"RecordFile assigned sapFileName={recording_context.sapFileName}.",
        )
        _set_session_recording(session, True)
        _append_recording_error(recording_context, f"SAP GUI native recording enabled with file {recording_context.sapFileName}.")
        _save_metadata(recording_context)
        _append_recording_error(recording_context, "Initial metadata written.")
        recording_context.startedEvent.set()
        _append_recording_error(recording_context, "Recording worker signaled startedEvent.")

        while not recording_context.stopEvent.wait(0.2):
            continue

        try:
            _append_recording_error(recording_context, "Stop requested. Disabling SAP GUI native recording.")
            _set_session_recording(session, False)
            _append_recording_error(recording_context, "SAP GUI native recording disabled.")
        except Exception as exc:
            recording_context.errorMessage = f"Failed to stop SAP GUI native recording cleanly: {str(exc) or repr(exc)}"
            _append_recording_exception(recording_context, "Failed to stop SAP GUI native recording cleanly", exc)
    except Exception as exc:
        recording_context.errorMessage = str(exc) or repr(exc)
        _append_recording_exception(recording_context, "Recording worker failed", exc)
        recording_context.startedEvent.set()
    finally:
        _append_recording_error(recording_context, "Recording worker finishing.")
        recording_context.finishedEvent.set()
        if pythoncom is not None:
            pythoncom.CoUninitialize()
            _append_recording_error(recording_context, "COM uninitialized.")


def _start_recording_event_listener(recording_context: SapGuiRecordingContext) -> None:
    """Start the external VBScript helper that listens for SAP GUI session events."""
    events_file_path, listener_log_path, listener_ready_path, listener_stop_path, raw_screenshots_folder = _get_recording_listener_paths(recording_context)
    raw_screenshots_folder.mkdir(parents=True, exist_ok=True)

    for stale_path in (events_file_path, listener_log_path, listener_ready_path, listener_stop_path):
        if stale_path.exists():
            stale_path.unlink()

    script_path = _get_event_listener_script_path()
    command = [
        "cscript.exe",
        "//nologo",
        str(script_path),
        recording_context.nativeSessionId,
        recording_context.folderPath,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(script_path.parent),
    )
    recording_context.listenerProcess = process
    recording_context.listenerStopFilePath = str(listener_stop_path)
    recording_context.listenerReadyFilePath = str(listener_ready_path)
    recording_context.listenerLogFilePath = str(listener_log_path)
    recording_context.listenerEventsFilePath = str(events_file_path)

    deadline = time.time() + 4.0
    while time.time() < deadline:
        if listener_ready_path.exists():
            return
        if process.poll() is not None:
            break
        time.sleep(0.2)

    log_suffix = ""
    if listener_log_path.exists():
        for encoding_name in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
            try:
                log_suffix = f" Listener log: {listener_log_path.read_text(encoding=encoding_name).strip()}"
                break
            except Exception:
                continue
    raise RuntimeError(f"Failed to start the SAP GUI event listener.{log_suffix}")


def _stop_recording_event_listener(recording_context: SapGuiRecordingContext) -> None:
    """Stop the external VBScript helper that listens for SAP GUI session events."""
    listener_process = recording_context.listenerProcess
    if listener_process is None:
        return

    stop_file_path = Path(recording_context.listenerStopFilePath)
    stop_file_path.parent.mkdir(parents=True, exist_ok=True)
    stop_file_path.write_text("stop", encoding="utf-8")

    try:
        listener_process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        listener_process.terminate()
        try:
            listener_process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            listener_process.kill()
            listener_process.wait(timeout=2.0)


def _read_jsonl_file(file_path: Path) -> list[dict]:
    """Read a JSONL file into a list of dictionaries."""
    if not file_path.exists():
        return []

    raw_text = ""
    for encoding_name in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            raw_text = file_path.read_text(encoding=encoding_name)
            break
        except Exception:
            continue
    if raw_text == "":
        return []

    rows: list[dict] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _build_screen_signature(event: dict) -> tuple[str, str, str, str]:
    """Build a stable technical screen signature from one event row."""
    return (
        str(event.get("transaction", "") or ""),
        str(event.get("program", "") or ""),
        str(event.get("screenNumber", "") or ""),
        str(event.get("windowTitle", "") or ""),
    )


def _compose_capture_group_to_file(group_events: list[dict], output_path: Path) -> bool:
    """Compose one screenshot group into a single BMP when coordinates are available."""
    if not group_events:
        return False

    if len(group_events) == 1:
        source_path = Path(group_events[0]["absoluteFilePath"])
        if not source_path.exists():
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output_path)
        return True

    valid_entries = []
    for item in group_events:
        try:
            valid_entries.append({
                "path": str(Path(item["absoluteFilePath"])),
                "left": int(item.get("left", 0)),
                "top": int(item.get("top", 0)),
                "width": int(item.get("width", 0)),
                "height": int(item.get("height", 0)),
                "windowId": str(item.get("windowId", "") or ""),
            })
        except Exception:
            return False

    if not valid_entries:
        return False

    min_left = min(item["left"] for item in valid_entries)
    min_top = min(item["top"] for item in valid_entries)
    max_right = max(item["left"] + max(item["width"], 1) for item in valid_entries)
    max_bottom = max(item["top"] + max(item["height"], 1) for item in valid_entries)
    canvas_width = max_right - min_left
    canvas_height = max_bottom - min_top
    if canvas_width <= 0 or canvas_height <= 0:
        return False

    manifest = {
        "output": str(output_path),
        "width": canvas_width,
        "height": canvas_height,
        "items": [
            {
                "path": item["path"],
                "left": item["left"] - min_left,
                "top": item["top"] - min_top,
                "windowId": item["windowId"],
            }
            for item in valid_entries
        ],
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    powershell_script = (
        "$manifest = Get-Content -Raw -Path '" + str(manifest_path).replace("'", "''") + "' | ConvertFrom-Json;"
        " Add-Type -AssemblyName System.Drawing;"
        " $bmp = New-Object System.Drawing.Bitmap([int]$manifest.width, [int]$manifest.height);"
        " $graphics = [System.Drawing.Graphics]::FromImage($bmp);"
        " $graphics.Clear([System.Drawing.Color]::White);"
        " $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::Black, 1);"
        " foreach ($item in $manifest.items) {"
        "   $img = [System.Drawing.Image]::FromFile([string]$item.path);"
        "   $graphics.DrawImage($img, [int]$item.left, [int]$item.top);"
        "   if ([string]$item.windowId -ne 'wnd[0]') {"
        "     $graphics.DrawRectangle($borderPen, [int]$item.left, [int]$item.top, [int]([Math]::Max(1, $img.Width - 1)), [int]([Math]::Max(1, $img.Height - 1)));"
        "   }"
        "   $img.Dispose();"
        " }"
        " $bmp.Save([string]$manifest.output, [System.Drawing.Imaging.ImageFormat]::Bmp);"
        " $borderPen.Dispose();"
        " $graphics.Dispose();"
        " $bmp.Dispose();"
    )

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", powershell_script],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_path.exists()
    except Exception:
        return False
    finally:
        if manifest_path.exists():
            manifest_path.unlink()


def _build_recording_artifacts(recording_context: SapGuiRecordingContext) -> tuple[list[dict], list[dict], list[dict]]:
    """Build final captures, screens, and transitions from the temporary event stream."""
    _, metadata_file_path, screenshots_folder = _get_recording_output_paths(recording_context)
    events_file_path, _, _, _, raw_screenshots_folder = _get_recording_listener_paths(recording_context)
    screenshots_folder.mkdir(parents=True, exist_ok=True)

    events = _read_jsonl_file(events_file_path)
    capture_groups: dict[str, list[dict]] = {}
    for event in events:
        if event.get("eventType") != "screenshotWindow":
            continue
        group_id = str(event.get("captureGroupId", "") or "")
        if not group_id:
            continue
        relative_file = str(event.get("screenshotFile", "") or "")
        absolute_file_path = (Path(recording_context.folderPath) / relative_file).resolve()
        event["absoluteFilePath"] = str(absolute_file_path)
        capture_groups.setdefault(group_id, []).append(event)

    captures: list[dict] = []
    capture_lookup: dict[str, dict] = {}
    for group_id, group_items in capture_groups.items():
        first_item = group_items[0]
        phase = str(first_item.get("phase", "") or "")
        program_name = str(first_item.get("program", "") or "unknown_program")
        screen_number = str(first_item.get("screenNumber", "") or "unknown_screen")
        output_name = f"{group_id}_{phase}_{program_name}_{screen_number}.bmp"
        final_output_path = screenshots_folder / output_name
        composed = _compose_capture_group_to_file(group_items, final_output_path)
        if not composed:
            continue

        capture_entry = {
            "captureGroupId": group_id,
            "phase": phase,
            "file": str(Path("screenshots") / output_name),
            "transaction": str(first_item.get("transaction", "") or ""),
            "program": program_name,
            "screenNumber": screen_number,
            "windowTitle": str(first_item.get("windowTitle", "") or ""),
            "windowCount": len(group_items),
        }
        captures.append(capture_entry)
        capture_lookup[group_id] = capture_entry

    screens: list[dict] = []
    transitions: list[dict] = []
    previous_signature: tuple[str, str, str, str] | None = None
    screen_index = 0

    for event in events:
        signature = _build_screen_signature(event)
        if not any(signature):
            continue
        if signature == previous_signature:
            continue

        screen_index += 1
        screen_entry = {
            "index": screen_index,
            "timestamp": str(event.get("timestamp", "") or ""),
            "transaction": signature[0],
            "program": signature[1],
            "screenNumber": signature[2],
            "windowTitle": signature[3],
            "screenshotFile": "",
        }

        capture_group_id = str(event.get("captureGroupId", "") or "")
        if capture_group_id and capture_group_id in capture_lookup:
            screen_entry["screenshotFile"] = capture_lookup[capture_group_id]["file"]
        else:
            matching_capture = next(
                (
                    capture for capture in captures
                    if (
                        capture["transaction"],
                        capture["program"],
                        capture["screenNumber"],
                        capture["windowTitle"],
                    ) == signature
                ),
                None,
            )
            if matching_capture is not None:
                screen_entry["screenshotFile"] = matching_capture["file"]

        screens.append(screen_entry)
        if previous_signature is not None:
            transitions.append({
                "fromIndex": screen_index - 1,
                "toIndex": screen_index,
                "timestamp": screen_entry["timestamp"],
                "triggerEventType": str(event.get("eventType", "") or ""),
            })
        previous_signature = signature

    metadata_payload = {
        "guiSessionId": recording_context.guiSessionId,
        "nativeSessionId": recording_context.nativeSessionId,
        "recordingFile": "recording.vbs",
        "logsFolder": "logs",
        "screenshotsFolder": "screenshots",
        "screens": screens,
        "transitions": transitions,
        "captures": captures,
    }
    metadata_file_path.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Temporary files are only needed while building the final metadata and screenshots.
    if events_file_path.exists():
        events_file_path.unlink()
    ready_file = _get_recording_listener_paths(recording_context)[2]
    stop_file = _get_recording_listener_paths(recording_context)[3]
    for temp_file in (ready_file, stop_file):
        if temp_file.exists():
            temp_file.unlink()
    if raw_screenshots_folder.exists():
        shutil.rmtree(raw_screenshots_folder, ignore_errors=True)
    temp_folder = _get_recording_temp_folder(recording_context)
    if temp_folder.exists():
        try:
            temp_folder.rmdir()
        except Exception:
            pass

    return captures, screens, transitions


def call_sap_gui_session_open(systemId: str) -> SapGuiSessionOpenResponse:
    """Open one new SAP GUI scripting session for a configured SAP system."""
    try:
        _require_scripting_dependencies()
        system_config = get_system_config(systemId)
        connection_name = (system_config.sap_gui_connection_name or "").strip()
        if not connection_name:
            raise ValueError(
                f"The configured SAP system '{system_config.id}' does not define sap_gui_connection_name in .env."
            )

        pythoncom.CoInitialize()
        _normalize_registered_sessions()
        _ensure_sap_logon_running()
        application = _get_scripting_application_with_retry()
        existing_native_session_ids = {
            item["nativeSessionId"]
            for item in _iter_visible_sessions(application)
            if item["nativeSessionId"]
        }
        connection = application.OpenConnection(connection_name, True)
        session = _get_connection_session(connection, existing_native_session_ids=existing_native_session_ids)
        _perform_logon_if_needed(
            session,
            client=system_config.client,
            user=system_config.user,
            password=system_config.password,
            language=system_config.language,
        )
        _handle_multiple_logon_popup(session)
        time.sleep(0.5)
        opened_session = _find_visible_session_by_native_id(application, _safe_getattr(session, "Id")) or {
            "nativeSessionId": _safe_getattr(session, "Id"),
            "connectionName": _read_connection_name(connection),
            "client": system_config.client,
            "user": system_config.user,
            "language": system_config.language,
        }

        native_session_id = opened_session["nativeSessionId"]
        context = _register_session(
            system_id=system_config.id,
            connection_name=opened_session["connectionName"],
            native_session_id=native_session_id,
        )

        return SapGuiSessionOpenResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": f"SAP GUI session opened successfully for system {system_config.id}.",
            "data": SapGuiSessionOpenOutput(
                guiSessionId=context.guiSessionId,
                systemId=system_config.id,
                connectionName=opened_session["connectionName"],
                nativeSessionId=native_session_id,
                client=opened_session.get("client", system_config.client),
                user=opened_session.get("user", system_config.user),
                language=opened_session.get("language", system_config.language) or system_config.language,
                attachedToExistingSession=False,
            ),
        })
    except KeyError as exc:
        return SapGuiSessionOpenResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except ValueError as exc:
        return SapGuiSessionOpenResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiSessionOpenResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to open the SAP GUI session: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_session_close(guiSessionId: str) -> SapGuiSessionCloseResponse:
    """Close one previously opened SAP GUI scripting session."""
    try:
        _require_scripting_dependencies()
        pythoncom.CoInitialize()
        context = _find_registered_context(guiSessionId)
        application = _get_scripting_application(max_wait_seconds=2.0)
        visible_session = _find_visible_session_by_native_id(application, context.nativeSessionId)

        if visible_session is None:
            GUI_SESSIONS.pop(guiSessionId, None)
            return SapGuiSessionCloseResponse.parse_obj({
                "result": True,
                "httpCode": 200,
                "httpReason": "OK",
                "message": f"The SAP GUI session for system {context.systemId} was already closed. The MCP registration was removed.",
                "data": SapGuiSessionCloseOutput(
                    guiSessionId=context.guiSessionId,
                    systemId=context.systemId,
                    connectionName=context.connectionName,
                    nativeSessionId=context.nativeSessionId,
                    alreadyClosed=True,
                ),
            })

        session = visible_session["session"]
        try:
            session.findById("wnd[0]/tbar[0]/okcd").text = "/nex"
            session.findById("wnd[0]").sendVKey(0)
        except Exception:
            session.findById("wnd[0]").close()

        GUI_SESSIONS.pop(guiSessionId, None)

        return SapGuiSessionCloseResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": f"SAP GUI session closed successfully for system {context.systemId}.",
            "data": SapGuiSessionCloseOutput(
                guiSessionId=context.guiSessionId,
                systemId=context.systemId,
                connectionName=context.connectionName,
                nativeSessionId=context.nativeSessionId,
                alreadyClosed=False,
            ),
        })
    except KeyError as exc:
        return SapGuiSessionCloseResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiSessionCloseResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to close the SAP GUI session: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_sessions_list() -> SapGuiSessionListResponse:
    """List the SAP GUI scripting sessions currently registered in the MCP server."""
    sessions = [
        SapGuiSessionListItem(
            guiSessionId=context.guiSessionId,
            nativeSessionId=context.nativeSessionId,
            systemId=context.systemId,
            connectionName=context.connectionName,
        )
        for context in GUI_SESSIONS.values()
    ]

    output = SapGuiSessionListOutput(
        sessions=sessions,
        totalCount=len(sessions),
    )
    return SapGuiSessionListResponse.parse_obj({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": "Registered SAP GUI sessions listed successfully.",
        "data": output,
    })


def call_sap_gui_session_screenshot(guiSessionId: str, filePath: str) -> SapGuiSessionScreenshotResponse:
    """Capture the current main window of one registered SAP GUI session to a local file."""
    try:
        _require_scripting_dependencies()
        target_path = ensure_absolute_file_path(filePath)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        pythoncom.CoInitialize()
        context, visible_session = _get_live_session_for_gui_session_id(guiSessionId)
        session = visible_session["session"]
        window = session.findById("wnd[0]")

        # SAP GUI writes bitmap screenshots through HardCopy.
        window.HardCopy(str(target_path), 2)
        size_bytes = target_path.stat().st_size

        return SapGuiSessionScreenshotResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "SAP GUI screenshot captured successfully.",
            "data": SapGuiSessionScreenshotOutput(
                guiSessionId=context.guiSessionId,
                nativeSessionId=context.nativeSessionId,
                filePath=str(target_path),
                imageFormat=target_path.suffix.lstrip(".").lower() or "bmp",
                sizeBytes=size_bytes,
                windowTitle=_read_window_title(session),
            ),
        })
    except KeyError as exc:
        return SapGuiSessionScreenshotResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except ValueError as exc:
        return SapGuiSessionScreenshotResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiSessionScreenshotResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to capture the SAP GUI screenshot: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_session_inspect(guiSessionId: str, maxDepth: int = 4) -> SapGuiSessionInspectResponse:
    """Inspect one registered SAP GUI session and return its control tree."""
    try:
        _require_scripting_dependencies()
        pythoncom.CoInitialize()
        context, visible_session = _get_live_session_for_gui_session_id(guiSessionId)
        session = visible_session["session"]
        info = getattr(session, "Info", None)

        controls: list[SapGuiControlInfo] = []
        for root_index in range(session.Children.Count):
            try:
                root_control = session.Children(root_index)
                controls.append(_build_control_tree(root_control, max_depth=max(0, maxDepth)))
            except Exception:
                continue

        return SapGuiSessionInspectResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "SAP GUI session inspected successfully.",
            "data": SapGuiSessionInspectOutput(
                guiSessionId=context.guiSessionId,
                nativeSessionId=context.nativeSessionId,
                systemId=context.systemId,
                connectionName=context.connectionName,
                windowTitle=_read_window_title(session),
                transaction=_safe_getattr(info, "Transaction"),
                program=_safe_getattr(info, "Program"),
                screenNumber=_safe_getattr(info, "ScreenNumber"),
                controls=controls,
            ),
        })
    except KeyError as exc:
        return SapGuiSessionInspectResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiSessionInspectResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to inspect the SAP GUI session: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_session_inspect_to_file(guiSessionId: str, filePath: str, maxDepth: int = 0) -> FileTransferResponse:
    """Inspect one registered SAP GUI session and write the structured result to a local JSON file."""
    try:
        inspect_response = call_sap_gui_session_inspect(
            guiSessionId=guiSessionId,
            maxDepth=maxDepth if maxDepth > 0 else 10_000,
        )
        if not inspect_response.result or inspect_response.data is None:
            return build_file_transfer_error(
                inspect_response.message or "Failed to inspect the SAP GUI session.",
                inspect_response.httpCode or 500,
                inspect_response.httpReason or "Internal Server Error",
            )

        payload = json.dumps(
            inspect_response.data.dict(),
            ensure_ascii=False,
            indent=2,
        )
        size_bytes = write_text_file(filePath, payload)
        return build_file_transfer_response(
            filePath=filePath,
            uri=f"sap-gui://sessions/{inspect_response.data.guiSessionId}/inspect",
            mimeType="application/json",
            sizeBytes=size_bytes,
            message="SAP GUI session inspection written to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to write SAP GUI session inspection to file: {str(exc)}")


def call_sap_gui_session_read_message(guiSessionId: str) -> SapGuiSessionReadMessageResponse:
    """Read the visible SAP message of one registered SAP GUI session."""
    try:
        _require_scripting_dependencies()
        pythoncom.CoInitialize()
        context, visible_session = _get_live_session_for_gui_session_id(guiSessionId)
        session = visible_session["session"]
        info = getattr(session, "Info", None)
        message = _read_visible_message(session)

        return SapGuiSessionReadMessageResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "SAP GUI visible message read successfully.",
            "data": SapGuiSessionReadMessageOutput(
                guiSessionId=context.guiSessionId,
                nativeSessionId=context.nativeSessionId,
                windowTitle=_read_window_title(session),
                transaction=_safe_getattr(info, "Transaction"),
                program=_safe_getattr(info, "Program"),
                screenNumber=_safe_getattr(info, "ScreenNumber"),
                message=message,
            ),
        })
    except KeyError as exc:
        return SapGuiSessionReadMessageResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiSessionReadMessageResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to read the SAP GUI visible message: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_session_actions(guiSessionId: str, request: SapGuiSessionActionsRequest) -> SapGuiSessionActionsResponse:
    """Execute one or more SAP GUI actions against a registered SAP GUI session."""
    try:
        _require_scripting_dependencies()
        if not request.actions:
            raise ValueError("actions must contain at least one SAP GUI action.")
        if request.waitForCompletion and int(request.timeoutSeconds) <= 0:
            raise ValueError("timeoutSeconds must be greater than 0 when waitForCompletion is true.")
        pythoncom.CoInitialize()
        context, visible_session = _get_live_session_for_gui_session_id(guiSessionId)
        session = visible_session["session"]
        executed_actions: list[SapGuiExecutedAction] = []
        for action in request.actions:
            executed_action = _execute_action(session, action)
            executed_actions.append(SapGuiExecutedAction(
                actionType=executed_action,
                controlId=action.controlId,
            ))
        if request.waitForCompletion:
            _wait_for_session_stable(
                session,
                timeout_seconds=float(request.timeoutSeconds),
            )
        info = getattr(session, "Info", None)
        message = _read_visible_message(session)

        return SapGuiSessionActionsResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "SAP GUI actions executed successfully.",
            "data": SapGuiSessionActionsOutput(
                guiSessionId=context.guiSessionId,
                nativeSessionId=context.nativeSessionId,
                actionsExecuted=executed_actions,
                windowTitle=_read_window_title(session),
                transaction=_safe_getattr(info, "Transaction"),
                program=_safe_getattr(info, "Program"),
                screenNumber=_safe_getattr(info, "ScreenNumber"),
                waitedForCompletion=bool(request.waitForCompletion),
                timeoutSeconds=int(request.timeoutSeconds),
                message=message,
            ),
        })
    except KeyError as exc:
        return SapGuiSessionActionsResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except ValueError as exc:
        return SapGuiSessionActionsResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except TimeoutError as exc:
        return SapGuiSessionActionsResponse.parse_obj({
            "result": False,
            "httpCode": 408,
            "httpReason": "Request Timeout",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiSessionActionsResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to execute the SAP GUI actions: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_recording_start(guiSessionId: str, folderPath: str) -> SapGuiRecordingStartResponse:
    """Start SAP GUI native recording for one registered session and point it to a local folder."""
    try:
        _require_scripting_dependencies()
        target_folder = ensure_absolute_file_path(folderPath)
        target_folder.mkdir(parents=True, exist_ok=True)
        sap_scripts_folder = _get_sap_gui_scripts_folder()

        sap_file_name = "recording.vbs"
        sap_recording_path = sap_scripts_folder / sap_file_name
        if sap_recording_path.exists():
            sap_recording_path.unlink()

        pythoncom.CoInitialize()
        context, visible_session = _get_live_session_for_gui_session_id(guiSessionId)
        if guiSessionId in GUI_RECORDINGS:
            raise ValueError("SAP GUI native recording is already active for this session.")

        recording_context = SapGuiRecordingContext(
            guiSessionId=context.guiSessionId,
            nativeSessionId=context.nativeSessionId,
            folderPath=str(target_folder),
            sapFileName=sap_file_name,
        )
        worker = threading.Thread(
            target=_recording_worker,
            args=(recording_context,),
            name=f"sap-gui-recording-{context.guiSessionId}",
            daemon=True,
        )
        recording_context.worker = worker
        GUI_RECORDINGS[guiSessionId] = recording_context
        worker.start()

        if not recording_context.startedEvent.wait(3.0):
            GUI_RECORDINGS.pop(guiSessionId, None)
            raise RuntimeError("Timed out while starting SAP GUI native recording.")

        if recording_context.errorMessage:
            GUI_RECORDINGS.pop(guiSessionId, None)
            raise RuntimeError(recording_context.errorMessage)

        _start_recording_event_listener(recording_context)
        _save_metadata(recording_context)

        return SapGuiRecordingStartResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "SAP GUI native recording started successfully.",
            "data": SapGuiRecordingStartOutput(
                guiSessionId=context.guiSessionId,
                nativeSessionId=context.nativeSessionId,
                folderPath=str(target_folder),
                recordingFilePath=str(target_folder / "recording.vbs"),
            ),
        })
    except KeyError as exc:
        return SapGuiRecordingStartResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except ValueError as exc:
        return SapGuiRecordingStartResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        recording_context = GUI_RECORDINGS.pop(guiSessionId, None)
        if recording_context is not None:
            try:
                _stop_recording_event_listener(recording_context)
            except Exception:
                pass
            try:
                recording_context.stopEvent.set()
                if recording_context.worker is not None:
                    recording_context.worker.join(timeout=5.0)
            except Exception:
                pass
        return SapGuiRecordingStartResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to start SAP GUI native recording: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()


def call_sap_gui_recording_stop(guiSessionId: str) -> SapGuiRecordingStopResponse:
    """Stop SAP GUI native recording for one registered session."""
    try:
        _require_scripting_dependencies()
        pythoncom.CoInitialize()
        context, _ = _get_live_session_for_gui_session_id(guiSessionId)
        recording_context = _get_recording_context(guiSessionId)
        _stop_recording_event_listener(recording_context)
        recording_context.stopEvent.set()
        if recording_context.worker is not None:
            recording_context.worker.join(timeout=5.0)
        if not recording_context.finishedEvent.is_set():
            raise RuntimeError("Timed out while stopping SAP GUI native recording.")
        if recording_context.errorMessage:
            raise RuntimeError(recording_context.errorMessage)

        recording_file_path, metadata_file_path_obj, _ = _get_recording_output_paths(recording_context)
        target_path = recording_file_path
        sap_recording_path = _get_sap_gui_scripts_folder() / recording_context.sapFileName
        if sap_recording_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sap_recording_path, target_path)

        captures, screens, transitions = _build_recording_artifacts(recording_context)
        size_bytes = target_path.stat().st_size if target_path.exists() else None
        recording_file_path = str(target_path)
        metadata_file_path = str(metadata_file_path_obj)
        screenshot_count = len(captures)
        GUI_RECORDINGS.pop(guiSessionId, None)

        return SapGuiRecordingStopResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "SAP GUI native recording stopped successfully.",
            "data": SapGuiRecordingStopOutput(
                guiSessionId=context.guiSessionId,
                nativeSessionId=context.nativeSessionId,
                folderPath=recording_context.folderPath,
                recordingFilePath=recording_file_path,
                metadataFilePath=metadata_file_path,
                screenshotCount=screenshot_count,
                sizeBytes=size_bytes,
            ),
        })
    except KeyError as exc:
        return SapGuiRecordingStopResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except ValueError as exc:
        return SapGuiRecordingStopResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SapGuiRecordingStopResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to stop SAP GUI native recording: {str(exc)}",
            "data": None,
        })
    finally:
        if pythoncom is not None:
            pythoncom.CoUninitialize()
