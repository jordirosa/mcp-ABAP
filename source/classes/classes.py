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


CLASSES_COLLECTION_URI = "/sap/bc/adt/oo/classes"
CLASS_OBJECT_TYPE = "CLAS/OC"


class ClassCreateRequest(BaseModel):
    """Metadata required to create one ABAP class object through ADT."""

    name: str = Field(..., description="Technical ABAP class name to create.")
    description: str = Field(..., description="Short class description.")
    packageName: str = Field("$TMP", description="Package that will own the class. Use $TMP for local objects.")
    language: str = Field("", description="Master language of the new object. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")
    visibility: str = Field("public", description="Class visibility, usually public, protected or private.")
    isFinal: bool = Field(True, description="Whether the created class should be flagged as final.")
    superClassName: str = Field("", description="Optional superclass name. Leave empty when the class has no superclass.")
    includeTestClasses: bool = Field(True, description="Whether the metadata payload should include the generated testclasses include.")


class ClassCreateOutput(BaseModel):
    """Result of creating one ABAP class object."""

    uri: str = Field(..., description="Repository object URI of the created class.")
    sourceUri: str = Field(..., description="Source URI of the created class source.")
    name: str = Field(..., description="Technical ABAP class name.")
    packageName: str = Field(..., description="Package that owns the class.")
    description: str = Field(..., description="Short class description.")
    objectType: str = Field(..., description="ADT object type used during creation.")
    transportNumber: str = Field("", description="Transport request number forwarded during creation when provided.")


class ClassCreateResponse(ApiResponse[ClassCreateOutput]):
    """Response model for creating one ABAP class."""


class ClassReadOutput(BaseModel):
    """Raw source code returned for one ABAP class."""

    uri: str = Field(..., description="Repository object URI of the class.")
    sourceUri: str = Field(..., description="Source URI used to read the class source.")
    name: str = Field(..., description="Technical ABAP class name.")
    content: str = Field(..., description="Raw ABAP source code of the class.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class ClassReadResponse(ApiResponse[ClassReadOutput]):
    """Response model for reading one ABAP class source."""


class ClassUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing ABAP class."""

    source: str = Field(..., description="Full ABAP source code to store in the class source.")


class ClassUpdateOutput(BaseModel):
    """Result of updating one existing ABAP class source."""

    uri: str = Field(..., description="Repository object URI of the class.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP class name.")
    transportNumber: str = Field("", description="Transport request number forwarded during the update when provided.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class ClassUpdateResponse(ApiResponse[ClassUpdateOutput]):
    """Response model for updating one ABAP class source."""


class ClassLockOutput(BaseModel):
    """Lock metadata returned for one ABAP class."""

    uri: str = Field(..., description="Repository object URI of the class.")
    name: str = Field(..., description="Technical ABAP class name.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the class.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class ClassLockResponse(ApiResponse[ClassLockOutput]):
    """Response model for locking or unlocking one ABAP class."""


def _normalize_class_name(name: str) -> str:
    """Normalize one ABAP class name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _class_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP class."""
    normalized_name = _normalize_class_name(name)
    return f"{CLASSES_COLLECTION_URI}/{normalized_name}"


def _class_source_uri(name: str) -> str:
    """Return the source URI of one ABAP class."""
    return f"{_class_object_uri(name)}/source/main"


def _class_symbols_uri(name: str) -> str:
    """Return the text symbols URI of one ABAP class."""
    normalized_name = _normalize_class_name(name)
    return f"/sap/bc/adt/textelements/classes/{normalized_name}/source/symbols"


def _build_class_create_payload(systemId: str, request: ClassCreateRequest) -> str:
    """Build the ADT XML payload required to create one ABAP class."""
    system_config = get_system_config(systemId)
    normalized_name = _normalize_class_name(request.name)
    language = str(request.language or "").strip() or system_config.language
    responsible = str(request.responsible or "").strip() or system_config.user

    payload: dict[str, object] = {
        "class:abapClass": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:class": "http://www.sap.com/adt/oo/classes",
            "@adtcore:description": request.description,
            "@adtcore:language": language,
            "@adtcore:name": normalized_name,
            "@adtcore:type": CLASS_OBJECT_TYPE,
            "@adtcore:masterLanguage": language,
            "@adtcore:masterSystem": system_config.id,
            "@adtcore:responsible": responsible,
            "@class:final": "true" if request.isFinal else "false",
            "@class:visibility": str(request.visibility or "public").strip() or "public",
            "adtcore:packageRef": {
                "@adtcore:name": request.packageName
            },
            "class:superClassRef": (
                {"@adtcore:name": str(request.superClassName or "").strip().upper()}
                if str(request.superClassName or "").strip()
                else None
            ),
        }
    }

    if request.includeTestClasses:
        payload["class:abapClass"]["class:include"] = {
            "@adtcore:name": CLASS_OBJECT_TYPE,
            "@adtcore:type": CLASS_OBJECT_TYPE,
            "@class:includeType": "testclasses",
        }

    return xmltodict.unparse(payload, pretty=False)


def call_class_lock(systemId: str, name: str) -> ClassLockResponse:
    """Lock one ABAP class through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the class because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(name)
        object_uri = _class_object_uri(normalized_name)
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
            return ClassLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the class.")

        return ClassLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class locked successfully.",
            "data": ClassLockOutput(
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
        return ClassLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the class: {str(exc)}",
            "data": None,
        })


def call_class_unlock(systemId: str, name: str, lockHandle: str) -> ClassLockResponse:
    """Unlock one ABAP class through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the class because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _class_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return ClassLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class unlock request: {response.text}",
                "data": None
            })

        return ClassLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class unlocked successfully.",
            "data": ClassLockOutput(
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
        return ClassLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the class: {str(exc)}",
            "data": None,
        })


def call_class_create(systemId: str, request: ClassCreateRequest, transportNumber: str = "") -> ClassCreateResponse:
    """Create one ABAP class object through the ADT classes collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the class because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(request.name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.oo.classes.v4+xml",
            "Accept": "application/xml",
        }
        if str(transportNumber or "").strip():
            headers["X-sap-adt-corrnr"] = str(transportNumber).strip()

        payload = _build_class_create_payload(systemId, request)
        response = get_session(systemId).post(
            f"{system_config.server}{CLASSES_COLLECTION_URI}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return ClassCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class creation request: {response.text}",
                "data": None
            })

        return ClassCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class created successfully.",
            "data": ClassCreateOutput(
                uri=_class_object_uri(normalized_name),
                sourceUri=_class_source_uri(normalized_name),
                name=normalized_name,
                packageName=request.packageName,
                description=request.description,
                objectType=CLASS_OBJECT_TYPE,
                transportNumber=str(transportNumber or ""),
            )
        })
    except ValueError as exc:
        return ClassCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the class: {str(exc)}",
            "data": None,
        })


def call_class_read(systemId: str, name: str) -> ClassReadResponse:
    """Read the raw source code of one ABAP class."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the class because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(name)
        source_uri = _class_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return ClassReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class read request: {response.text}",
                "data": None
            })

        return ClassReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class source read successfully.",
            "data": ClassReadOutput(
                uri=_class_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return ClassReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the class source: {str(exc)}",
            "data": None,
        })


def call_class_update(systemId: str, name: str, lockHandle: str, request: ClassUpdateRequest, transportNumber: str = "") -> ClassUpdateResponse:
    """Update the raw source code of one existing ABAP class."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the class because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _class_source_uri(normalized_name)
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
            return ClassUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class update request: {response.text}",
                "data": None
            })

        return ClassUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class source updated successfully.",
            "data": ClassUpdateOutput(
                uri=_class_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                transportNumber=str(transportNumber or ""),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return ClassUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the class source: {str(exc)}",
            "data": None,
        })


def call_class_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one ABAP class using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _class_object_uri(name), transportNumber)
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_class_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one ABAP class source to a local file."""
    try:
        response = call_class_read(systemId, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the class source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Class source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the class source to file: {str(exc)}")


def call_class_write_from_file(systemId: str, name: str, filePath: str, transportNumber: str = "") -> FileTransferResponse:
    """Upload one ABAP class source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_class_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the class.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_class_update(
                systemId,
                name,
                lock_response.data.lockHandle,
                ClassUpdateRequest(source=content),
                transportNumber,
            )
        finally:
            call_class_unlock(systemId, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the class source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Class source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the class source from file: {str(exc)}")


def call_class_symbols_read(systemId: str, name: str) -> SourceSymbolsReadResponse:
    """Read the text symbols of one ABAP class."""
    normalized_name = _normalize_class_name(name)
    return call_source_symbols_read(systemId, _class_symbols_uri(normalized_name), normalized_name)


def call_class_symbols_update(systemId: str, name: str, request: SourceSymbolsUpdateRequest) -> SourceSymbolsUpdateResponse:
    """Update the text symbols of one ABAP class with automatic locking."""
    normalized_name = _normalize_class_name(name)
    lock_response = call_source_symbols_lock(systemId, _class_symbols_uri(normalized_name), normalized_name)
    if not lock_response.result or not lock_response.data:
        return SourceSymbolsUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the class.",
            "data": None
        })

    try:
        return call_source_symbols_update(
            systemId=systemId,
            symbolsUri=_class_symbols_uri(normalized_name),
            objectName=normalized_name,
            request=request,
            lockHandle=lock_response.data.lockHandle,
        )
    finally:
        call_source_symbols_unlock(systemId, _class_symbols_uri(normalized_name), normalized_name, lock_response.data.lockHandle)


def call_class_symbols_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download the text symbols of one ABAP class to a local file."""
    normalized_name = _normalize_class_name(name)
    return call_source_symbols_read_to_file(systemId, _class_symbols_uri(normalized_name), normalized_name, filePath)


def call_class_symbols_write_from_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Upload the text symbols of one ABAP class from a local file with automatic locking."""
    normalized_name = _normalize_class_name(name)
    lock_response = call_source_symbols_lock(systemId, _class_symbols_uri(normalized_name), normalized_name)
    if not lock_response.result or not lock_response.data:
        return build_file_transfer_error(
            lock_response.message or "Failed to lock the class.",
            lock_response.httpCode or 500,
            lock_response.httpReason or "Internal Server Error",
        )

    try:
        return call_source_symbols_write_from_file(
            systemId=systemId,
            symbolsUri=_class_symbols_uri(normalized_name),
            objectName=normalized_name,
            filePath=filePath,
            lockHandle=lock_response.data.lockHandle,
        )
    finally:
        call_source_symbols_unlock(systemId, _class_symbols_uri(normalized_name), normalized_name, lock_response.data.lockHandle)
