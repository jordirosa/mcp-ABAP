import xmltodict
from urllib.parse import quote

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from deletion.deletion import call_deletion_delete, DeletionDeleteResponse
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


INTERFACES_COLLECTION_URI = "/sap/bc/adt/oo/interfaces"
INTERFACE_OBJECT_TYPE = "INTF/OI"


class InterfaceCreateRequest(BaseModel):
    """Metadata required to create one ABAP interface object through ADT."""

    name: str = Field(..., description="Technical ABAP interface name to create.")
    description: str = Field(..., description="Short interface description.")
    packageName: str = Field("$TMP", description="Package that will own the interface. Use $TMP for local objects.")
    language: str = Field("", description="Master language of the new object. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")


class InterfaceCreateOutput(BaseModel):
    """Result of creating one ABAP interface object."""

    uri: str = Field(..., description="Repository object URI of the created interface.")
    sourceUri: str = Field(..., description="Source URI of the created interface source.")
    name: str = Field(..., description="Technical ABAP interface name.")
    packageName: str = Field(..., description="Package that owns the interface.")
    description: str = Field(..., description="Short interface description.")
    objectType: str = Field(..., description="ADT object type used during creation.")
    transportNumber: str = Field("", description="Transport request number forwarded during creation when provided.")


class InterfaceCreateResponse(ApiResponse[InterfaceCreateOutput]):
    """Response model for creating one ABAP interface."""


class InterfaceReadOutput(BaseModel):
    """Raw source code returned for one ABAP interface."""

    uri: str = Field(..., description="Repository object URI of the interface.")
    sourceUri: str = Field(..., description="Source URI used to read the interface source.")
    name: str = Field(..., description="Technical ABAP interface name.")
    content: str = Field(..., description="Raw ABAP source code of the interface.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class InterfaceReadResponse(ApiResponse[InterfaceReadOutput]):
    """Response model for reading one ABAP interface source."""


class InterfaceUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing ABAP interface."""

    source: str = Field(..., description="Full ABAP source code to store in the interface source.")


class InterfaceUpdateOutput(BaseModel):
    """Result of updating one existing ABAP interface source."""

    uri: str = Field(..., description="Repository object URI of the interface.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP interface name.")
    transportNumber: str = Field("", description="Transport request number forwarded during the update when provided.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class InterfaceUpdateResponse(ApiResponse[InterfaceUpdateOutput]):
    """Response model for updating one ABAP interface source."""


class InterfaceLockOutput(BaseModel):
    """Lock metadata returned for one ABAP interface."""

    uri: str = Field(..., description="Repository object URI of the interface.")
    name: str = Field(..., description="Technical ABAP interface name.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the interface.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class InterfaceLockResponse(ApiResponse[InterfaceLockOutput]):
    """Response model for locking or unlocking one ABAP interface."""


def _normalize_interface_name(name: str) -> str:
    """Normalize one ABAP interface name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _interface_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP interface."""
    normalized_name = _normalize_interface_name(name)
    return f"{INTERFACES_COLLECTION_URI}/{normalized_name}"


def _interface_source_uri(name: str) -> str:
    """Return the source URI of one ABAP interface."""
    return f"{_interface_object_uri(name)}/source/main"


def _build_interface_create_payload(systemId: str, request: InterfaceCreateRequest) -> str:
    """Build the ADT XML payload required to create one ABAP interface."""
    system_config = get_system_config(systemId)
    normalized_name = _normalize_interface_name(request.name)
    language = str(request.language or "").strip() or system_config.language
    responsible = str(request.responsible or "").strip() or system_config.user

    payload = {
        "intf:abapInterface": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:intf": "http://www.sap.com/adt/oo/interfaces",
            "@adtcore:description": request.description,
            "@adtcore:language": language,
            "@adtcore:name": normalized_name,
            "@adtcore:type": INTERFACE_OBJECT_TYPE,
            "@adtcore:masterLanguage": language,
            "@adtcore:masterSystem": system_config.id,
            "@adtcore:responsible": responsible,
            "adtcore:packageRef": {
                "@adtcore:name": request.packageName
            },
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_interface_lock(systemId: str, name: str) -> InterfaceLockResponse:
    """Lock one ABAP interface through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return InterfaceLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the interface because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_interface_name(name)
        object_uri = _interface_object_uri(normalized_name)
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
            return InterfaceLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the interface lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the interface.")

        return InterfaceLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Interface locked successfully.",
            "data": InterfaceLockOutput(
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
        return InterfaceLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return InterfaceLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the interface: {str(exc)}",
            "data": None,
        })


def call_interface_unlock(systemId: str, name: str, lockHandle: str) -> InterfaceLockResponse:
    """Unlock one ABAP interface through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return InterfaceLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the interface because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_interface_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _interface_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return InterfaceLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the interface unlock request: {response.text}",
                "data": None
            })

        return InterfaceLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Interface unlocked successfully.",
            "data": InterfaceLockOutput(
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
        return InterfaceLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return InterfaceLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the interface: {str(exc)}",
            "data": None,
        })


def call_interface_create(systemId: str, request: InterfaceCreateRequest, transportNumber: str = "") -> InterfaceCreateResponse:
    """Create one ABAP interface object through the ADT interfaces collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return InterfaceCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the interface because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_interface_name(request.name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.oo.interfaces.v5+xml",
            "Accept": "application/xml",
        }
        params = {}
        if str(transportNumber or "").strip():
            params["corrNr"] = str(transportNumber).strip()

        payload = _build_interface_create_payload(systemId, request)
        response = get_session(systemId).post(
            f"{system_config.server}{INTERFACES_COLLECTION_URI}",
            headers=headers,
            params=params,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return InterfaceCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the interface creation request: {response.text}",
                "data": None
            })

        return InterfaceCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Interface created successfully.",
            "data": InterfaceCreateOutput(
                uri=_interface_object_uri(normalized_name),
                sourceUri=_interface_source_uri(normalized_name),
                name=normalized_name,
                packageName=request.packageName,
                description=request.description,
                objectType=INTERFACE_OBJECT_TYPE,
                transportNumber=str(transportNumber or ""),
            )
        })
    except ValueError as exc:
        return InterfaceCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return InterfaceCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the interface: {str(exc)}",
            "data": None,
        })


def call_interface_read(systemId: str, name: str) -> InterfaceReadResponse:
    """Read the raw source code of one ABAP interface."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return InterfaceReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the interface because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_interface_name(name)
        source_uri = _interface_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return InterfaceReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the interface read request: {response.text}",
                "data": None
            })

        return InterfaceReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Interface source read successfully.",
            "data": InterfaceReadOutput(
                uri=_interface_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return InterfaceReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return InterfaceReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the interface source: {str(exc)}",
            "data": None,
        })


def call_interface_update(systemId: str, name: str, lockHandle: str, request: InterfaceUpdateRequest, transportNumber: str = "") -> InterfaceUpdateResponse:
    """Update the raw source code of one existing ABAP interface."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return InterfaceUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the interface because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_interface_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _interface_source_uri(normalized_name)
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
            return InterfaceUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the interface update request: {response.text}",
                "data": None
            })

        return InterfaceUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Interface source updated successfully.",
            "data": InterfaceUpdateOutput(
                uri=_interface_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                transportNumber=str(transportNumber or ""),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return InterfaceUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return InterfaceUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the interface source: {str(exc)}",
            "data": None,
        })


def call_interface_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one ABAP interface using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _interface_object_uri(name), transportNumber)
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_interface_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one ABAP interface source to a local file."""
    try:
        response = call_interface_read(systemId, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the interface source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Interface source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the interface source to file: {str(exc)}")


def call_interface_write_from_file(systemId: str, name: str, filePath: str, transportNumber: str = "") -> FileTransferResponse:
    """Upload one ABAP interface source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_interface_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the interface.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_interface_update(
                systemId,
                name,
                lock_response.data.lockHandle,
                InterfaceUpdateRequest(source=content),
                transportNumber,
            )
        finally:
            call_interface_unlock(systemId, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the interface source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Interface source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the interface source from file: {str(exc)}")
