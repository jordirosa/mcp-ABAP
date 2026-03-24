from fastmcp import FastMCP
from pydantic import Field

from activation.activation import *
from configuration import *
from connection.connection import *
from cts.cts import *
from deletion.deletion import *
from ddic.db.settings import *
from ddic.dataelements.dataelements import *
from ddic.domains.domains import *
from ddic.tables.tables import *
from generics import FileTransferOutput, FileTransferResponse
from gui.gui import *
from info_repository.info_repository import *
from utils import *

mcp = FastMCP(name="ABAP Tools - MCP Server", version="1.0.0")
print("FastMCP server object created.")

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
    filePath: str = Field(..., description="Absolute local file path where the screenshot of the current SAP GUI main window should be written.")
) -> SapGuiSessionScreenshotResponse:
    """Capture a screenshot of the current SAP GUI main window for one registered session and store it in a local file."""
    return call_sap_gui_session_screenshot(guiSessionId, filePath)


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
        return DdicTableDbSettingsUpdateResponse.parse_obj({
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
        return DdicTableUpdateResponse.parse_obj({
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
        return DdicDataElementUpdateResponse.parse_obj({
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
        return DdicDomainUpdateResponse.parse_obj({
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

if __name__ == "__main__":
    print("\n--- Initiating FastMCP server through __main__ ---")
    mcp.run()
