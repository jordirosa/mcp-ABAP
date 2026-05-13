import xmltodict
from urllib.parse import quote

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from deletion.deletion import call_deletion_delete, DeletionDeleteResponse
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


FUNCTION_GROUPS_COLLECTION_URI = "/sap/bc/adt/functions/groups"
FUNCTION_MODULE_OBJECT_TYPE = "FUGR/FF"
FUNCTION_GROUP_OBJECT_TYPE = "FUGR/F"


class FunctionModuleCreateRequest(BaseModel):
    """Metadata required to create one ABAP function module through ADT."""

    name: str = Field(..., description="Technical ABAP function module name to create.")
    description: str = Field(..., description="Short function module description.")
    functionGroupName: str = Field(..., description="Technical name of the parent function group that will contain the function module.")


class FunctionModuleCreateOutput(BaseModel):
    """Result of creating one ABAP function module."""

    uri: str = Field(..., description="Repository object URI of the created function module.")
    sourceUri: str = Field(..., description="Source URI of the created function module source.")
    name: str = Field(..., description="Technical ABAP function module name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module.")
    description: str = Field(..., description="Short function module description.")
    objectType: str = Field(..., description="ADT object type used during creation.")


class FunctionModuleCreateResponse(ApiResponse[FunctionModuleCreateOutput]):
    """Response model for creating one ABAP function module."""


class FunctionModuleReadOutput(BaseModel):
    """Raw source code returned for one ABAP function module."""

    uri: str = Field(..., description="Repository object URI of the function module.")
    sourceUri: str = Field(..., description="Source URI used to read the function module source.")
    name: str = Field(..., description="Technical ABAP function module name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module.")
    content: str = Field(..., description="Raw ABAP source code of the function module.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class FunctionModuleReadResponse(ApiResponse[FunctionModuleReadOutput]):
    """Response model for reading one ABAP function module source."""


class FunctionModuleUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing ABAP function module."""

    source: str = Field(..., description="Full ABAP source code to store in the function module source.")


class FunctionModuleUpdateOutput(BaseModel):
    """Result of updating one existing ABAP function module source."""

    uri: str = Field(..., description="Repository object URI of the function module.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP function module name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class FunctionModuleUpdateResponse(ApiResponse[FunctionModuleUpdateOutput]):
    """Response model for updating one ABAP function module source."""


class FunctionModuleLockOutput(BaseModel):
    """Lock metadata returned for one ABAP function module."""

    uri: str = Field(..., description="Repository object URI of the function module.")
    name: str = Field(..., description="Technical ABAP function module name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the module.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the function module.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class FunctionModuleLockResponse(ApiResponse[FunctionModuleLockOutput]):
    """Response model for locking or unlocking one ABAP function module."""


def _normalize_function_group_name(name: str) -> str:
    """Normalize one ABAP function group name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("functionGroupName is required.")
    return normalized


def _normalize_function_module_name(name: str) -> str:
    """Normalize one ABAP function module name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _function_group_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP function group."""
    normalized_name = _normalize_function_group_name(name)
    return f"{FUNCTION_GROUPS_COLLECTION_URI}/{normalized_name}"


def _function_module_collection_uri(functionGroupName: str) -> str:
    """Return the collection URI that owns the function modules of one function group."""
    return f"{_function_group_object_uri(functionGroupName)}/fmodules"


def _function_module_object_uri(functionGroupName: str, name: str) -> str:
    """Return the repository object URI of one ABAP function module."""
    normalized_name = _normalize_function_module_name(name)
    return f"{_function_module_collection_uri(functionGroupName)}/{normalized_name}"


def _function_module_source_uri(functionGroupName: str, name: str) -> str:
    """Return the source URI of one ABAP function module."""
    return f"{_function_module_object_uri(functionGroupName, name)}/source/main"


def _build_function_module_create_payload(request: FunctionModuleCreateRequest) -> str:
    """Build the ADT XML payload required to create one ABAP function module."""
    normalized_name = _normalize_function_module_name(request.name)
    normalized_group_name = _normalize_function_group_name(request.functionGroupName)

    payload = {
        "fmodule:abapFunctionModule": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:fmodule": "http://www.sap.com/adt/functions/fmodules",
            "@adtcore:description": request.description,
            "@adtcore:name": normalized_name,
            "@adtcore:type": FUNCTION_MODULE_OBJECT_TYPE,
            "adtcore:containerRef": {
                "@adtcore:name": normalized_group_name,
                "@adtcore:type": FUNCTION_GROUP_OBJECT_TYPE,
                "@adtcore:uri": _function_group_object_uri(normalized_group_name),
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_function_module_lock(systemId: str, functionGroupName: str, name: str) -> FunctionModuleLockResponse:
    """Lock one ABAP function module through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionModuleLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the function module because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_module_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        object_uri = _function_module_object_uri(normalized_group_name, normalized_name)
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
            return FunctionModuleLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function module lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the function module.")

        return FunctionModuleLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function module locked successfully.",
            "data": FunctionModuleLockOutput(
                uri=object_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                lockHandle=lock_handle,
                corrnr=str(data.get("CORRNR", "") or ""),
                corruser=str(data.get("CORRUSER", "") or ""),
                corrtext=str(data.get("CORRTEXT", "") or ""),
                isLocal=str(data.get("IS_LOCAL", "") or "").upper() == "X",
            )
        })
    except ValueError as exc:
        return FunctionModuleLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionModuleLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the function module: {str(exc)}",
            "data": None,
        })


def call_function_module_unlock(systemId: str, functionGroupName: str, name: str, lockHandle: str) -> FunctionModuleLockResponse:
    """Unlock one ABAP function module through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionModuleLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the function module because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_module_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _function_module_object_uri(normalized_group_name, normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return FunctionModuleLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function module unlock request: {response.text}",
                "data": None
            })

        return FunctionModuleLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function module unlocked successfully.",
            "data": FunctionModuleLockOutput(
                uri=object_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                lockHandle=normalized_lock_handle,
                corrnr="",
                corruser="",
                corrtext="",
                isLocal=False,
            )
        })
    except ValueError as exc:
        return FunctionModuleLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionModuleLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the function module: {str(exc)}",
            "data": None,
        })


def call_function_module_create(systemId: str, request: FunctionModuleCreateRequest) -> FunctionModuleCreateResponse:
    """Create one ABAP function module through the ADT function modules collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionModuleCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the function module because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_module_name(request.name)
        normalized_group_name = _normalize_function_group_name(request.functionGroupName)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.functions.fmodules+xml",
            "Accept": "application/xml",
        }

        payload = _build_function_module_create_payload(request)
        response = get_session(systemId).post(
            f"{system_config.server}{_function_module_collection_uri(normalized_group_name)}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code not in {200, 201}:
            return FunctionModuleCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function module creation request: {response.text}",
                "data": None
            })

        location = response.headers.get("Location", "") or _function_module_object_uri(normalized_group_name, normalized_name)
        source_uri = f"{location}/source/main" if location else _function_module_source_uri(normalized_group_name, normalized_name)

        return FunctionModuleCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function module created successfully.",
            "data": FunctionModuleCreateOutput(
                uri=location,
                sourceUri=source_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                description=request.description,
                objectType=FUNCTION_MODULE_OBJECT_TYPE,
            )
        })
    except ValueError as exc:
        return FunctionModuleCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionModuleCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the function module: {str(exc)}",
            "data": None,
        })


def call_function_module_read(systemId: str, functionGroupName: str, name: str) -> FunctionModuleReadResponse:
    """Read the raw source code of one ABAP function module."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionModuleReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the function module because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_module_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        source_uri = _function_module_source_uri(normalized_group_name, normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return FunctionModuleReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function module read request: {response.text}",
                "data": None
            })

        return FunctionModuleReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function module source read successfully.",
            "data": FunctionModuleReadOutput(
                uri=_function_module_object_uri(normalized_group_name, normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return FunctionModuleReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionModuleReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the function module source: {str(exc)}",
            "data": None,
        })


def call_function_module_update(systemId: str, functionGroupName: str, name: str, lockHandle: str, request: FunctionModuleUpdateRequest) -> FunctionModuleUpdateResponse:
    """Update the raw source code of one existing ABAP function module."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionModuleUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the function module because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_module_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _function_module_source_uri(normalized_group_name, normalized_name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "text/plain",
        }

        response = get_session(systemId).put(
            f"{system_config.server}{source_uri}?lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
            data=request.source.encode("utf-8"),
        )

        if response.status_code not in {200, 204}:
            return FunctionModuleUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function module update request: {response.text}",
                "data": None
            })

        return FunctionModuleUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function module source updated successfully.",
            "data": FunctionModuleUpdateOutput(
                uri=_function_module_object_uri(normalized_group_name, normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return FunctionModuleUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionModuleUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the function module source: {str(exc)}",
            "data": None,
        })


def call_function_module_delete(systemId: str, functionGroupName: str, name: str) -> DeletionDeleteResponse:
    """Delete one ABAP function module using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _function_module_object_uri(functionGroupName, name), "")
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_function_module_read_to_file(systemId: str, functionGroupName: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one ABAP function module source to a local file."""
    try:
        response = call_function_module_read(systemId, functionGroupName, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the function module source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Function module source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the function module source to file: {str(exc)}")


def call_function_module_write_from_file(systemId: str, functionGroupName: str, name: str, filePath: str) -> FileTransferResponse:
    """Upload one ABAP function module source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_function_module_lock(systemId, functionGroupName, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the function module.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_function_module_update(
                systemId,
                functionGroupName,
                name,
                lock_response.data.lockHandle,
                FunctionModuleUpdateRequest(source=content),
            )
        finally:
            call_function_module_unlock(systemId, functionGroupName, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the function module source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Function module source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the function module source from file: {str(exc)}")
