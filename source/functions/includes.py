import xmltodict
from urllib.parse import quote

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from deletion.deletion import call_deletion_delete, DeletionDeleteResponse
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


FUNCTION_GROUPS_COLLECTION_URI = "/sap/bc/adt/functions/groups"
FUNCTION_GROUP_OBJECT_TYPE = "FUGR/F"
FUNCTION_INCLUDE_OBJECT_TYPE = "FUGR/I"


class FunctionIncludeCreateRequest(BaseModel):
    """Metadata required to create one function group include through ADT."""

    name: str = Field(..., description="Technical ABAP function group include name to create.")
    description: str = Field(..., description="Short function group include description.")
    functionGroupName: str = Field(..., description="Technical name of the parent function group that will contain the include.")


class FunctionIncludeCreateOutput(BaseModel):
    """Result of creating one function group include."""

    uri: str = Field(..., description="Repository object URI of the created include.")
    sourceUri: str = Field(..., description="Source URI of the created include source.")
    name: str = Field(..., description="Technical ABAP function group include name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include.")
    description: str = Field(..., description="Short include description.")
    objectType: str = Field(..., description="ADT object type used during creation.")


class FunctionIncludeCreateResponse(ApiResponse[FunctionIncludeCreateOutput]):
    """Response model for creating one function group include."""


class FunctionIncludeReadOutput(BaseModel):
    """Raw source code returned for one function group include."""

    uri: str = Field(..., description="Repository object URI of the include.")
    sourceUri: str = Field(..., description="Source URI used to read the include source.")
    name: str = Field(..., description="Technical ABAP function group include name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include.")
    content: str = Field(..., description="Raw ABAP source code of the include.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class FunctionIncludeReadResponse(ApiResponse[FunctionIncludeReadOutput]):
    """Response model for reading one function group include source."""


class FunctionIncludeUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing function group include."""

    source: str = Field(..., description="Full ABAP source code to store in the include source.")


class FunctionIncludeUpdateOutput(BaseModel):
    """Result of updating one existing function group include source."""

    uri: str = Field(..., description="Repository object URI of the include.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP function group include name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class FunctionIncludeUpdateResponse(ApiResponse[FunctionIncludeUpdateOutput]):
    """Response model for updating one function group include source."""


class FunctionIncludeLockOutput(BaseModel):
    """Lock metadata returned for one function group include."""

    uri: str = Field(..., description="Repository object URI of the include.")
    name: str = Field(..., description="Technical ABAP function group include name.")
    functionGroupName: str = Field(..., description="Technical ABAP function group name that owns the include.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the include.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class FunctionIncludeLockResponse(ApiResponse[FunctionIncludeLockOutput]):
    """Response model for locking or unlocking one function group include."""


def _normalize_function_group_name(name: str) -> str:
    """Normalize one ABAP function group name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("functionGroupName is required.")
    return normalized


def _normalize_function_include_name(name: str) -> str:
    """Normalize one ABAP function group include name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _function_group_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP function group."""
    normalized_name = _normalize_function_group_name(name)
    return f"{FUNCTION_GROUPS_COLLECTION_URI}/{normalized_name}"


def _function_include_collection_uri(functionGroupName: str) -> str:
    """Return the collection URI that owns the includes of one function group."""
    return f"{_function_group_object_uri(functionGroupName)}/includes"


def _function_include_object_uri(functionGroupName: str, name: str) -> str:
    """Return the repository object URI of one function group include."""
    normalized_name = _normalize_function_include_name(name)
    return f"{_function_include_collection_uri(functionGroupName)}/{normalized_name}"


def _function_include_source_uri(functionGroupName: str, name: str) -> str:
    """Return the source URI of one function group include."""
    return f"{_function_include_object_uri(functionGroupName, name)}/source/main"


def _build_function_include_create_payload(request: FunctionIncludeCreateRequest) -> str:
    """Build the ADT XML payload required to create one function group include."""
    normalized_name = _normalize_function_include_name(request.name)
    normalized_group_name = _normalize_function_group_name(request.functionGroupName)

    payload = {
        "finclude:abapFunctionGroupInclude": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:finclude": "http://www.sap.com/adt/functions/fincludes",
            "@adtcore:description": request.description,
            "@adtcore:name": normalized_name,
            "@adtcore:type": FUNCTION_INCLUDE_OBJECT_TYPE,
            "adtcore:containerRef": {
                "@adtcore:name": normalized_group_name,
                "@adtcore:type": FUNCTION_GROUP_OBJECT_TYPE,
                "@adtcore:uri": _function_group_object_uri(normalized_group_name),
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_function_include_lock(systemId: str, functionGroupName: str, name: str) -> FunctionIncludeLockResponse:
    """Lock one function group include through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionIncludeLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the function group include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_include_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        object_uri = _function_include_object_uri(normalized_group_name, normalized_name)
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
            return FunctionIncludeLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group include lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the function group include.")

        return FunctionIncludeLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group include locked successfully.",
            "data": FunctionIncludeLockOutput(
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
        return FunctionIncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionIncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the function group include: {str(exc)}",
            "data": None,
        })


def call_function_include_unlock(systemId: str, functionGroupName: str, name: str, lockHandle: str) -> FunctionIncludeLockResponse:
    """Unlock one function group include through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionIncludeLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the function group include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_include_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _function_include_object_uri(normalized_group_name, normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return FunctionIncludeLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group include unlock request: {response.text}",
                "data": None
            })

        return FunctionIncludeLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group include unlocked successfully.",
            "data": FunctionIncludeLockOutput(
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
        return FunctionIncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionIncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the function group include: {str(exc)}",
            "data": None,
        })


def call_function_include_create(systemId: str, request: FunctionIncludeCreateRequest) -> FunctionIncludeCreateResponse:
    """Create one function group include through the ADT function group includes collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionIncludeCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the function group include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_include_name(request.name)
        normalized_group_name = _normalize_function_group_name(request.functionGroupName)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.functions.fincludes.v2+xml",
            "Accept": "application/xml",
        }

        payload = _build_function_include_create_payload(request)
        response = get_session(systemId).post(
            f"{system_config.server}{_function_include_collection_uri(normalized_group_name)}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return FunctionIncludeCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group include creation request: {response.text}",
                "data": None
            })

        return FunctionIncludeCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group include created successfully.",
            "data": FunctionIncludeCreateOutput(
                uri=_function_include_object_uri(normalized_group_name, normalized_name),
                sourceUri=_function_include_source_uri(normalized_group_name, normalized_name),
                name=normalized_name,
                functionGroupName=normalized_group_name,
                description=request.description,
                objectType=FUNCTION_INCLUDE_OBJECT_TYPE,
            )
        })
    except ValueError as exc:
        return FunctionIncludeCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionIncludeCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the function group include: {str(exc)}",
            "data": None,
        })


def call_function_include_read(systemId: str, functionGroupName: str, name: str) -> FunctionIncludeReadResponse:
    """Read the raw source code of one function group include."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionIncludeReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the function group include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_include_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        source_uri = _function_include_source_uri(normalized_group_name, normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return FunctionIncludeReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group include read request: {response.text}",
                "data": None
            })

        return FunctionIncludeReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group include source read successfully.",
            "data": FunctionIncludeReadOutput(
                uri=_function_include_object_uri(normalized_group_name, normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return FunctionIncludeReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionIncludeReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the function group include source: {str(exc)}",
            "data": None,
        })


def call_function_include_update(systemId: str, functionGroupName: str, name: str, lockHandle: str, request: FunctionIncludeUpdateRequest) -> FunctionIncludeUpdateResponse:
    """Update the raw source code of one existing function group include."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return FunctionIncludeUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the function group include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_function_include_name(name)
        normalized_group_name = _normalize_function_group_name(functionGroupName)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _function_include_source_uri(normalized_group_name, normalized_name)
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
            return FunctionIncludeUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the function group include update request: {response.text}",
                "data": None
            })

        return FunctionIncludeUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Function group include source updated successfully.",
            "data": FunctionIncludeUpdateOutput(
                uri=_function_include_object_uri(normalized_group_name, normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                functionGroupName=normalized_group_name,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return FunctionIncludeUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return FunctionIncludeUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the function group include source: {str(exc)}",
            "data": None,
        })


def call_function_include_delete(systemId: str, functionGroupName: str, name: str) -> DeletionDeleteResponse:
    """Delete one function group include using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _function_include_object_uri(functionGroupName, name), "")
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_function_include_read_to_file(systemId: str, functionGroupName: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one function group include source to a local file."""
    try:
        response = call_function_include_read(systemId, functionGroupName, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the function group include source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Function group include source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the function group include source to file: {str(exc)}")


def call_function_include_write_from_file(systemId: str, functionGroupName: str, name: str, filePath: str) -> FileTransferResponse:
    """Upload one function group include source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_function_include_lock(systemId, functionGroupName, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the function group include.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_function_include_update(
                systemId,
                functionGroupName,
                name,
                lock_response.data.lockHandle,
                FunctionIncludeUpdateRequest(source=content),
            )
        finally:
            call_function_include_unlock(systemId, functionGroupName, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the function group include source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Function group include source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the function group include source from file: {str(exc)}")
