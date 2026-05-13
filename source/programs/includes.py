from urllib.parse import quote

from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from deletion.deletion import call_deletion_delete, DeletionDeleteResponse
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


INCLUDES_COLLECTION_URI = "/sap/bc/adt/programs/includes"
INCLUDE_OBJECT_TYPE = "PROG/I"


class IncludeCreateRequest(BaseModel):
    """Metadata required to create one ABAP include object through ADT."""

    name: str = Field(..., description="Technical ABAP include name to create.")
    description: str = Field(..., description="Short include description.")
    packageName: str = Field("$TMP", description="Package that will own the include. Use $TMP for local objects.")
    language: str = Field("", description="Master language of the new object. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")


class IncludeCreateOutput(BaseModel):
    """Result of creating one ABAP include object."""

    uri: str = Field(..., description="Repository object URI of the created include.")
    sourceUri: str = Field(..., description="Source URI of the created include source.")
    name: str = Field(..., description="Technical ABAP include name.")
    packageName: str = Field(..., description="Package that owns the include.")
    description: str = Field(..., description="Short include description.")
    objectType: str = Field(..., description="ADT object type used during creation.")
    transportNumber: str = Field("", description="Transport request number forwarded during creation when provided.")


class IncludeCreateResponse(ApiResponse[IncludeCreateOutput]):
    """Response model for creating one ABAP include."""


class IncludeReadOutput(BaseModel):
    """Raw source code returned for one ABAP include."""

    uri: str = Field(..., description="Repository object URI of the include.")
    sourceUri: str = Field(..., description="Source URI used to read the include source.")
    name: str = Field(..., description="Technical ABAP include name.")
    content: str = Field(..., description="Raw ABAP source code of the include.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class IncludeReadResponse(ApiResponse[IncludeReadOutput]):
    """Response model for reading one ABAP include source."""


class IncludeUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing include."""

    source: str = Field(..., description="Full ABAP source code to store in the include source.")


class IncludeUpdateOutput(BaseModel):
    """Result of updating one existing ABAP include source."""

    uri: str = Field(..., description="Repository object URI of the include.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP include name.")
    transportNumber: str = Field("", description="Transport request number forwarded during the update when provided.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class IncludeUpdateResponse(ApiResponse[IncludeUpdateOutput]):
    """Response model for updating one ABAP include source."""


class IncludeLockOutput(BaseModel):
    """Lock metadata returned for one ABAP include."""

    uri: str = Field(..., description="Repository object URI of the include.")
    name: str = Field(..., description="Technical ABAP include name.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the include.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class IncludeLockResponse(ApiResponse[IncludeLockOutput]):
    """Response model for locking or unlocking one ABAP include."""


def _normalize_include_name(name: str) -> str:
    """Normalize one ABAP include name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _include_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP include."""
    normalized_name = _normalize_include_name(name)
    return f"{INCLUDES_COLLECTION_URI}/{normalized_name}"


def _include_source_uri(name: str) -> str:
    """Return the source URI of one ABAP include."""
    return f"{_include_object_uri(name)}/source/main"


def _build_include_create_payload(systemId: str, request: IncludeCreateRequest) -> str:
    """Build the ADT XML payload required to create one ABAP include."""
    system_config = get_system_config(systemId)
    normalized_name = _normalize_include_name(request.name)
    language = str(request.language or "").strip() or system_config.language
    responsible = str(request.responsible or "").strip() or system_config.user

    payload = {
        "include:abapInclude": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:include": "http://www.sap.com/adt/programs/includes",
            "@adtcore:description": request.description,
            "@adtcore:language": language,
            "@adtcore:name": normalized_name,
            "@adtcore:type": INCLUDE_OBJECT_TYPE,
            "@adtcore:masterLanguage": language,
            "@adtcore:masterSystem": system_config.id,
            "@adtcore:responsible": responsible,
            "adtcore:packageRef": {
                "@adtcore:name": request.packageName
            }
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_include_lock(systemId: str, name: str) -> IncludeLockResponse:
    """Lock one ABAP include through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return IncludeLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_include_name(name)
        object_uri = _include_object_uri(normalized_name)
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
            return IncludeLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the include lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the include.")

        return IncludeLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Include locked successfully.",
            "data": IncludeLockOutput(
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
        return IncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return IncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the include: {str(exc)}",
            "data": None,
        })


def call_include_unlock(systemId: str, name: str, lockHandle: str) -> IncludeLockResponse:
    """Unlock one ABAP include through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return IncludeLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_include_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _include_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return IncludeLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the include unlock request: {response.text}",
                "data": None
            })

        return IncludeLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Include unlocked successfully.",
            "data": IncludeLockOutput(
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
        return IncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return IncludeLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the include: {str(exc)}",
            "data": None,
        })


def call_include_create(systemId: str, request: IncludeCreateRequest, transportNumber: str = "") -> IncludeCreateResponse:
    """Create one ABAP include through the ADT includes collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return IncludeCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_include_name(request.name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.programs.includes.v2+xml",
            "Accept": "application/xml",
        }
        if str(transportNumber or "").strip():
            headers["X-sap-adt-corrnr"] = str(transportNumber).strip()

        payload = _build_include_create_payload(systemId, request)
        response = get_session(systemId).post(
            f"{system_config.server}{INCLUDES_COLLECTION_URI}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return IncludeCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the include creation request: {response.text}",
                "data": None
            })

        return IncludeCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Include created successfully.",
            "data": IncludeCreateOutput(
                uri=_include_object_uri(normalized_name),
                sourceUri=_include_source_uri(normalized_name),
                name=normalized_name,
                packageName=request.packageName,
                description=request.description,
                objectType=INCLUDE_OBJECT_TYPE,
                transportNumber=str(transportNumber or ""),
            )
        })
    except ValueError as exc:
        return IncludeCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return IncludeCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the include: {str(exc)}",
            "data": None,
        })


def call_include_read(systemId: str, name: str) -> IncludeReadResponse:
    """Read the raw source code of one ABAP include."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return IncludeReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_include_name(name)
        source_uri = _include_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return IncludeReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the include read request: {response.text}",
                "data": None
            })

        return IncludeReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Include source read successfully.",
            "data": IncludeReadOutput(
                uri=_include_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return IncludeReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return IncludeReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the include source: {str(exc)}",
            "data": None,
        })


def call_include_update(systemId: str, name: str, lockHandle: str, request: IncludeUpdateRequest, transportNumber: str = "") -> IncludeUpdateResponse:
    """Update the raw source code of one existing ABAP include."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return IncludeUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_include_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _include_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "text/plain",
        }
        if str(transportNumber or "").strip():
            headers["X-sap-adt-corrnr"] = str(transportNumber).strip()

        response = get_session(systemId).put(
            f"{system_config.server}{source_uri}?lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
            data=request.source.encode("utf-8"),
        )

        if response.status_code not in {200, 204}:
            return IncludeUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the include update request: {response.text}",
                "data": None
            })

        return IncludeUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Include source updated successfully.",
            "data": IncludeUpdateOutput(
                uri=_include_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                transportNumber=str(transportNumber or ""),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return IncludeUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return IncludeUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the include source: {str(exc)}",
            "data": None,
        })


def call_include_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one ABAP include using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _include_object_uri(name), transportNumber)
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_include_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one ABAP include source to a local file."""
    try:
        response = call_include_read(systemId, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the include source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Include source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the include source to file: {str(exc)}")


def call_include_write_from_file(systemId: str, name: str, filePath: str, transportNumber: str = "") -> FileTransferResponse:
    """Upload one ABAP include source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_include_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the include.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_include_update(
                systemId,
                name,
                lock_response.data.lockHandle,
                IncludeUpdateRequest(source=content),
                transportNumber,
            )
        finally:
            call_include_unlock(systemId, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the include source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Include source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the include source from file: {str(exc)}")
