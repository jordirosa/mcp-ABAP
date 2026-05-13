from urllib.parse import quote

from pydantic import BaseModel, Field
import xmltodict

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


PROGRAMS_COLLECTION_URI = "/sap/bc/adt/programs/programs"
PROGRAM_OBJECT_TYPE = "PROG/P"


class ProgramCreateRequest(BaseModel):
    """Metadata required to create one ABAP program object through ADT."""

    name: str = Field(..., description="Technical ABAP program name to create.")
    description: str = Field(..., description="Short program description.")
    packageName: str = Field("$TMP", description="Package that will own the program. Use $TMP for local objects.")
    language: str = Field("", description="Master language of the new object. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")


class ProgramCreateOutput(BaseModel):
    """Result of creating one ABAP program object."""

    uri: str = Field(..., description="Repository object URI of the created program.")
    sourceUri: str = Field(..., description="Source URI of the created program source.")
    name: str = Field(..., description="Technical ABAP program name.")
    packageName: str = Field(..., description="Package that owns the program.")
    description: str = Field(..., description="Short program description.")
    objectType: str = Field(..., description="ADT object type used during creation.")
    transportNumber: str = Field("", description="Transport request number forwarded during creation when provided.")


class ProgramCreateResponse(ApiResponse[ProgramCreateOutput]):
    """Response model for creating one ABAP program."""


class ProgramReadOutput(BaseModel):
    """Raw source code returned for one ABAP program."""

    uri: str = Field(..., description="Repository object URI of the program.")
    sourceUri: str = Field(..., description="Source URI used to read the program source.")
    name: str = Field(..., description="Technical ABAP program name.")
    content: str = Field(..., description="Raw ABAP source code of the program.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class ProgramReadResponse(ApiResponse[ProgramReadOutput]):
    """Response model for reading one ABAP program source."""


class ProgramUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one existing program."""

    source: str = Field(..., description="Full ABAP source code to store in the program source.")


class ProgramUpdateOutput(BaseModel):
    """Result of updating one existing ABAP program source."""

    uri: str = Field(..., description="Repository object URI of the program.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical ABAP program name.")
    transportNumber: str = Field("", description="Transport request number forwarded during the update when provided.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class ProgramUpdateResponse(ApiResponse[ProgramUpdateOutput]):
    """Response model for updating one ABAP program source."""


class ProgramLockOutput(BaseModel):
    """Lock metadata returned for one ABAP program."""

    uri: str = Field(..., description="Repository object URI of the program.")
    name: str = Field(..., description="Technical ABAP program name.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the program.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class ProgramLockResponse(ApiResponse[ProgramLockOutput]):
    """Response model for locking or unlocking one ABAP program."""


def _normalize_program_name(name: str) -> str:
    """Normalize one ABAP program name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _program_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP program."""
    normalized_name = _normalize_program_name(name)
    return f"{PROGRAMS_COLLECTION_URI}/{normalized_name}"


def _program_source_uri(name: str) -> str:
    """Return the source URI of one ABAP program."""
    return f"{_program_object_uri(name)}/source/main"


def _program_symbols_uri(name: str) -> str:
    """Return the text symbols URI of one ABAP program."""
    normalized_name = _normalize_program_name(name)
    return f"/sap/bc/adt/textelements/programs/{normalized_name}/source/symbols"


def _build_program_create_payload(systemId: str, request: ProgramCreateRequest) -> str:
    """Build the ADT XML payload required to create one ABAP program."""
    system_config = get_system_config(systemId)
    normalized_name = _normalize_program_name(request.name)
    language = str(request.language or "").strip() or system_config.language
    responsible = str(request.responsible or "").strip() or system_config.user

    payload = {
        "program:abapProgram": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:program": "http://www.sap.com/adt/programs/programs",
            "@adtcore:description": request.description,
            "@adtcore:language": language,
            "@adtcore:name": normalized_name,
            "@adtcore:type": PROGRAM_OBJECT_TYPE,
            "@adtcore:masterLanguage": language,
            "@adtcore:masterSystem": system_config.id,
            "@adtcore:responsible": responsible,
            "adtcore:packageRef": {
                "@adtcore:name": request.packageName
            }
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_program_lock(systemId: str, name: str) -> ProgramLockResponse:
    """Lock one ABAP program through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ProgramLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the program because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_program_name(name)
        object_uri = _program_object_uri(normalized_name)
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
            return ProgramLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the program lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the program.")

        return ProgramLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Program locked successfully.",
            "data": ProgramLockOutput(
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
        return ProgramLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ProgramLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the program: {str(exc)}",
            "data": None,
        })


def call_program_unlock(systemId: str, name: str, lockHandle: str) -> ProgramLockResponse:
    """Unlock one ABAP program through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ProgramLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the program because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_program_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _program_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return ProgramLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the program unlock request: {response.text}",
                "data": None
            })

        return ProgramLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Program unlocked successfully.",
            "data": ProgramLockOutput(
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
        return ProgramLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ProgramLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the program: {str(exc)}",
            "data": None,
        })


def call_program_create(systemId: str, request: ProgramCreateRequest, transportNumber: str = "") -> ProgramCreateResponse:
    """Create one ABAP program object through the ADT programs collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ProgramCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the program because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_program_name(request.name)
        system_config = get_system_config(systemId)
        headers = {
            "Content-Type": "application/vnd.sap.adt.programs.programs.v3+xml",
            "Accept": "application/xml",
        }
        if str(transportNumber or "").strip():
            headers["X-sap-adt-corrnr"] = str(transportNumber).strip()

        payload = _build_program_create_payload(systemId, request)
        response = get_session(systemId).post(
            f"{system_config.server}{PROGRAMS_COLLECTION_URI}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 200:
            return ProgramCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the program creation request: {response.text}",
                "data": None
            })

        return ProgramCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Program created successfully.",
            "data": ProgramCreateOutput(
                uri=_program_object_uri(normalized_name),
                sourceUri=_program_source_uri(normalized_name),
                name=normalized_name,
                packageName=request.packageName,
                description=request.description,
                objectType=PROGRAM_OBJECT_TYPE,
                transportNumber=str(transportNumber or ""),
            )
        })
    except ValueError as exc:
        return ProgramCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ProgramCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the program: {str(exc)}",
            "data": None,
        })


def call_program_read(systemId: str, name: str) -> ProgramReadResponse:
    """Read the raw source code of one ABAP program."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ProgramReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the program because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_program_name(name)
        source_uri = _program_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return ProgramReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the program read request: {response.text}",
                "data": None
            })

        return ProgramReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Program source read successfully.",
            "data": ProgramReadOutput(
                uri=_program_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return ProgramReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ProgramReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the program source: {str(exc)}",
            "data": None,
        })


def call_program_update(systemId: str, name: str, lockHandle: str, request: ProgramUpdateRequest, transportNumber: str = "") -> ProgramUpdateResponse:
    """Update the raw source code of one existing ABAP program."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ProgramUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the program because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_program_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _program_source_uri(normalized_name)
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
            return ProgramUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the program update request: {response.text}",
                "data": None
            })

        return ProgramUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Program source updated successfully.",
            "data": ProgramUpdateOutput(
                uri=_program_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                transportNumber=str(transportNumber or ""),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return ProgramUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ProgramUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the program source: {str(exc)}",
            "data": None,
        })


def call_program_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one ABAP program using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _program_object_uri(name), transportNumber)
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_program_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one ABAP program source to a local file."""
    try:
        response = call_program_read(systemId, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the program source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Program source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the program source to file: {str(exc)}")


def call_program_write_from_file(systemId: str, name: str, filePath: str, transportNumber: str = "") -> FileTransferResponse:
    """Upload one ABAP program source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_program_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the program.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_program_update(
                systemId,
                name,
                lock_response.data.lockHandle,
                ProgramUpdateRequest(source=content),
                transportNumber,
            )
        finally:
            call_program_unlock(systemId, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the program source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Program source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the program source from file: {str(exc)}")


def call_program_symbols_read(systemId: str, name: str) -> SourceSymbolsReadResponse:
    """Read the text symbols of one ABAP program."""
    normalized_name = _normalize_program_name(name)
    return call_source_symbols_read(systemId, _program_symbols_uri(normalized_name), normalized_name)


def call_program_symbols_update(systemId: str, name: str, request: SourceSymbolsUpdateRequest) -> SourceSymbolsUpdateResponse:
    """Update the text symbols of one ABAP program with automatic locking."""
    normalized_name = _normalize_program_name(name)
    lock_response = call_source_symbols_lock(systemId, _program_symbols_uri(normalized_name), normalized_name)
    if not lock_response.result or not lock_response.data:
        return SourceSymbolsUpdateResponse.model_validate({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock the program.",
            "data": None
        })

    try:
        return call_source_symbols_update(
            systemId=systemId,
            symbolsUri=_program_symbols_uri(normalized_name),
            objectName=normalized_name,
            request=request,
            lockHandle=lock_response.data.lockHandle,
        )
    finally:
        call_source_symbols_unlock(systemId, _program_symbols_uri(normalized_name), normalized_name, lock_response.data.lockHandle)


def call_program_symbols_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download the text symbols of one ABAP program to a local file."""
    normalized_name = _normalize_program_name(name)
    return call_source_symbols_read_to_file(systemId, _program_symbols_uri(normalized_name), normalized_name, filePath)


def call_program_symbols_write_from_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Upload the text symbols of one ABAP program from a local file with automatic locking."""
    normalized_name = _normalize_program_name(name)
    lock_response = call_source_symbols_lock(systemId, _program_symbols_uri(normalized_name), normalized_name)
    if not lock_response.result or not lock_response.data:
        return build_file_transfer_error(
            lock_response.message or "Failed to lock the program.",
            lock_response.httpCode or 500,
            lock_response.httpReason or "Internal Server Error",
        )

    try:
        return call_source_symbols_write_from_file(
            systemId=systemId,
            symbolsUri=_program_symbols_uri(normalized_name),
            objectName=normalized_name,
            filePath=filePath,
            lockHandle=lock_response.data.lockHandle,
        )
    finally:
        call_source_symbols_unlock(systemId, _program_symbols_uri(normalized_name), normalized_name, lock_response.data.lockHandle)
