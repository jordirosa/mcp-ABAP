import xmltodict
from urllib.parse import quote

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from deletion.deletion import call_deletion_delete, DeletionDeleteResponse
from generics import ApiResponse, FileTransferResponse
from source.symbols import (
    SourceSymbolsLockResponse,
    SourceSymbolsReadResponse,
    SourceSymbolsUpdateRequest,
    SourceSymbolsUpdateResponse,
    call_source_symbols_lock,
    call_source_symbols_read,
    call_source_symbols_read_to_file,
    call_source_symbols_unlock,
    call_source_symbols_update,
    call_source_symbols_write_from_file,
)
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


FUNCTION_GROUPS_COLLECTION_URI = "/sap/bc/adt/functions/groups"
FUNCTION_GROUP_OBJECT_TYPE = "FUGR/F"


class FunctionGroupCreateRequest(BaseModel):
    """Metadata required to create one ABAP function group through ADT."""

    name: str = Field(..., description="Technical ABAP function group name to create.")
    description: str = Field(..., description="Short function group description.")
    packageName: str = Field("$TMP", description="Package that will own the function group. Use $TMP for local objects.")
    language: str = Field("", description="Master language of the new object. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")


class FunctionGroupCreateOutput(BaseModel):
    """Result of creating one ABAP function group."""

    uri: str = Field(..., description="Repository object URI of the created function group.")
    sourceUri: str = Field(..., description="Source URI of the created function group source.")
    name: str = Field(..., description="Technical ABAP function group name.")
    packageName: str = Field(..., description="Package that owns the function group.")
    description: str = Field(..., description="Short function group description.")
    objectType: str = Field(..., description="ADT object type used during creation.")
    transportNumber: str = Field("", description="Transport request number forwarded during creation when provided.")


class FunctionGroupCreateResponse(ApiResponse[FunctionGroupCreateOutput]):
    """Response model for creating one ABAP function group."""


class FunctionGroupReadOutput(BaseModel):
    """Raw source code returned for one ABAP function group."""

    uri: str = Field(..., description="Repository object URI of the function group.")
    sourceUri: str = Field(..., description="Source URI used to read the function group source.")
    name: str = Field(..., description="Technical ABAP function group name.")
    content: str = Field(..., description="Raw ABAP source code of the function group.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class FunctionGroupReadResponse(ApiResponse[FunctionGroupReadOutput]):
    """Response model for reading one ABAP function group source."""


class FunctionGroupUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing ABAP function group."""

    source: str = Field(..., description="Full ABAP source code to store in the function group source.")


class FunctionGroupUpdateOutput(BaseModel):
    """Result of updating one existing ABAP function group source."""

    uri: str = Field(..., description="Repository object URI of the function group.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP function group name.")
    transportNumber: str = Field("", description="Transport request number forwarded during the update when provided.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class FunctionGroupUpdateResponse(ApiResponse[FunctionGroupUpdateOutput]):
    """Response model for updating one ABAP function group source."""


class FunctionGroupLockOutput(BaseModel):
    """Lock metadata returned for one ABAP function group."""

    uri: str = Field(..., description="Repository object URI of the function group.")
    name: str = Field(..., description="Technical ABAP function group name.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the function group.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class FunctionGroupLockResponse(ApiResponse[FunctionGroupLockOutput]):
    """Response model for locking or unlocking one ABAP function group."""


def _normalize_function_group_name(name: str) -> str:
    """Normalize one ABAP function group name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _function_group_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP function group."""
    normalized_name = _normalize_function_group_name(name)
    return f"{FUNCTION_GROUPS_COLLECTION_URI}/{normalized_name}"


def _function_group_source_uri(name: str) -> str:
    """Return the source URI of one ABAP function group."""
    return f"{_function_group_object_uri(name)}/source/main"


def _function_group_symbols_uri(name: str) -> str:
    """Return the text symbols URI of one ABAP function group."""
    normalized_name = _normalize_function_group_name(name)
    return f"/sap/bc/adt/textelements/functiongroups/{normalized_name}/source/symbols"


def _build_function_group_create_payload(systemId: str, request: FunctionGroupCreateRequest) -> str:
    """Build the ADT XML payload required to create one ABAP function group."""
    system_config = get_system_config(systemId)
    normalized_name = _normalize_function_group_name(request.name)
    language = str(request.language or "").strip() or system_config.language
    responsible = str(request.responsible or "").strip() or system_config.user

    payload = {
        "group:abapFunctionGroup": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:group": "http://www.sap.com/adt/functions/groups",
            "@adtcore:description": request.description,
            "@adtcore:language": language,
            "@adtcore:name": normalized_name,
            "@adtcore:type": FUNCTION_GROUP_OBJECT_TYPE,
            "@adtcore:masterLanguage": language,
            "@adtcore:masterSystem": system_config.id,
            "@adtcore:responsible": responsible,
            "adtcore:packageRef": {
                "@adtcore:name": request.packageName
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_function_group_lock(systemId: str, name: str) -> FunctionGroupLockResponse:
    """Lock one ABAP function group through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionGroupLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the function group because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_group_name(name)
        object_uri = _function_group_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(
            sessionType="stateful",
            extra={
                "Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
            }
        )

        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=LOCK&accessMode=MODIFY",
            headers=headers,
        )

        if response.status_code != 200:
            return FunctionGroupLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the function group.")

        return FunctionGroupLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group locked successfully.",
            "data": FunctionGroupLockOutput(
                uri=object_uri,
                name=normalized_name,
                lockHandle=lock_handle,
                corrnr=str(data.get("CORRNR", "") or ""),
                corruser=str(data.get("CORRUSER", "") or ""),
                corrtext=str(data.get("CORRTEXT", "") or ""),
                isLocal=str(data.get("IS_LOCAL", "") or "").upper() == "X",
            )
        })
    except ValueError as exc:
        return FunctionGroupLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionGroupLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the function group: {str(exc)}",
            "data": None,
        })


def call_function_group_unlock(systemId: str, name: str, lockHandle: str) -> FunctionGroupLockResponse:
    """Unlock one ABAP function group through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionGroupLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the function group because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_group_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _function_group_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return FunctionGroupLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group unlock request: {response.text}",
                "data": None
            })

        return FunctionGroupLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group unlocked successfully.",
            "data": FunctionGroupLockOutput(
                uri=object_uri,
                name=normalized_name,
                lockHandle=normalized_lock_handle,
                corrnr="",
                corruser="",
                corrtext="",
                isLocal=False,
            )
        })
    except ValueError as exc:
        return FunctionGroupLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionGroupLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the function group: {str(exc)}",
            "data": None,
        })


def call_function_group_create(systemId: str, request: FunctionGroupCreateRequest, transportNumber: str = "") -> FunctionGroupCreateResponse:
    """Create one ABAP function group through the ADT function groups collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionGroupCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the function group because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_group_name(request.name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.functions.groups.v3+xml",
            "Accept": "application/xml",
        }
        params = {}
        if str(transportNumber or "").strip():
            params["corrNr"] = str(transportNumber).strip()

        payload = _build_function_group_create_payload(systemId, request)
        response = get_session(systemId).post(
            f"{system_config.server}{FUNCTION_GROUPS_COLLECTION_URI}",
            headers=headers,
            params=params,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return FunctionGroupCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group creation request: {response.text}",
                "data": None
            })

        return FunctionGroupCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group created successfully.",
            "data": FunctionGroupCreateOutput(
                uri=_function_group_object_uri(normalized_name),
                sourceUri=_function_group_source_uri(normalized_name),
                name=normalized_name,
                packageName=request.packageName,
                description=request.description,
                objectType=FUNCTION_GROUP_OBJECT_TYPE,
                transportNumber=str(transportNumber or ""),
            )
        })
    except ValueError as exc:
        return FunctionGroupCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionGroupCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the function group: {str(exc)}",
            "data": None,
        })


def call_function_group_read(systemId: str, name: str) -> FunctionGroupReadResponse:
    """Read the raw source code of one ABAP function group."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionGroupReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the function group because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_group_name(name)
        source_uri = _function_group_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return FunctionGroupReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group read request: {response.text}",
                "data": None
            })

        return FunctionGroupReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group source read successfully.",
            "data": FunctionGroupReadOutput(
                uri=_function_group_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return FunctionGroupReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionGroupReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the function group source: {str(exc)}",
            "data": None,
        })


def call_function_group_update(systemId: str, name: str, lockHandle: str, request: FunctionGroupUpdateRequest, transportNumber: str = "") -> FunctionGroupUpdateResponse:
    """Update the raw source code of one existing ABAP function group."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionGroupUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the function group because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_group_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _function_group_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "text/plain",
        }
        params = {"lockHandle": normalized_lock_handle}
        if str(transportNumber or "").strip():
            params["corrNr"] = str(transportNumber).strip()

        response = get_session(systemId).put(
            f"{system_config.server}{source_uri}",
            headers=headers,
            params=params,
            data=request.source.encode("utf-8"),
        )

        if response.status_code not in {200, 204}:
            return FunctionGroupUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group update request: {response.text}",
                "data": None
            })

        return FunctionGroupUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group source updated successfully.",
            "data": FunctionGroupUpdateOutput(
                uri=_function_group_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                transportNumber=str(transportNumber or ""),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return FunctionGroupUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionGroupUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the function group source: {str(exc)}",
            "data": None,
        })


def call_function_group_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one ABAP function group using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _function_group_object_uri(name), transportNumber)
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_function_group_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one ABAP function group source to a local file."""
    try:
        response = call_function_group_read(systemId, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the function group source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Function group source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the function group source to file: {str(exc)}")


def call_function_group_write_from_file(systemId: str, name: str, filePath: str, transportNumber: str = "") -> FileTransferResponse:
    """Upload one ABAP function group source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_function_group_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the function group.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_function_group_update(
                systemId,
                name,
                lock_response.data.lockHandle,
                FunctionGroupUpdateRequest(source=content),
                transportNumber,
            )
        finally:
            call_function_group_unlock(systemId, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the function group source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Function group source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the function group source from file: {str(exc)}")


def call_function_group_symbols_read(systemId: str, name: str) -> SourceSymbolsReadResponse:
    """Read the text symbols of one ABAP function group."""
    normalized_name = _normalize_function_group_name(name)
    return call_source_symbols_read(systemId, _function_group_symbols_uri(normalized_name), normalized_name)


def call_function_group_symbols_update(systemId: str, name: str, request: SourceSymbolsUpdateRequest) -> SourceSymbolsUpdateResponse:
    """Update the text symbols of one ABAP function group with automatic locking."""
    normalized_name = _normalize_function_group_name(name)
    lock_response = call_source_symbols_lock(systemId, _function_group_symbols_uri(normalized_name), normalized_name)
    if not lock_response.result or not lock_response.data:
        return SourceSymbolsUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the function group.",
            "data": None
        })

    try:
        return call_source_symbols_update(
            systemId=systemId,
            symbolsUri=_function_group_symbols_uri(normalized_name),
            objectName=normalized_name,
            request=request,
            lockHandle=lock_response.data.lockHandle,
        )
    finally:
        call_source_symbols_unlock(systemId, _function_group_symbols_uri(normalized_name), normalized_name, lock_response.data.lockHandle)


def call_function_group_symbols_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download the text symbols of one ABAP function group to a local file."""
    normalized_name = _normalize_function_group_name(name)
    return call_source_symbols_read_to_file(systemId, _function_group_symbols_uri(normalized_name), normalized_name, filePath)


def call_function_group_symbols_write_from_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Upload the text symbols of one ABAP function group from a local file with automatic locking."""
    normalized_name = _normalize_function_group_name(name)
    lock_response = call_source_symbols_lock(systemId, _function_group_symbols_uri(normalized_name), normalized_name)
    if not lock_response.result or not lock_response.data:
        return build_file_transfer_error(
            lock_response.message or "Failed to lock the function group.",
            lock_response.httpCode or 500,
            lock_response.httpReason or "Internal Server Error",
        )

    try:
        return call_source_symbols_write_from_file(
            systemId=systemId,
            symbolsUri=_function_group_symbols_uri(normalized_name),
            objectName=normalized_name,
            filePath=filePath,
            lockHandle=lock_response.data.lockHandle,
        )
    finally:
        call_source_symbols_unlock(systemId, _function_group_symbols_uri(normalized_name), normalized_name, lock_response.data.lockHandle)
