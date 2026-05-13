from urllib.parse import quote

from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from connection.connection import build_adt_headers, ensure_login
from deletion.deletion import call_deletion_delete, DeletionDeleteResponse
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


DDL_SOURCES_COLLECTION_URI = "/sap/bc/adt/ddic/ddl/sources"
DDL_SOURCE_OBJECT_TYPE = "DDLS/DF"


class DdicDdlSourceCreateOutput(BaseModel):
    """Result of creating one CDS DDL source object."""

    uri: str = Field(..., description="Repository object URI of the created DDL source.")
    sourceUri: str = Field(..., description="Source URI of the created DDL source content.")
    name: str = Field(..., description="Technical CDS DDL source name.")
    packageName: str = Field(..., description="Package that owns the DDL source.")
    description: str = Field(..., description="Short DDL source description.")
    transportNumber: str = Field("", description="Transport request number forwarded during creation when provided.")


class DdicDdlSourceCreateResponse(ApiResponse[DdicDdlSourceCreateOutput]):
    """Response model for creating one CDS DDL source."""


class DdicDdlSourceReadOutput(BaseModel):
    """Raw source returned for one CDS DDL source."""

    uri: str = Field(..., description="Repository object URI of the DDL source.")
    sourceUri: str = Field(..., description="Source URI used to read the DDL source content.")
    name: str = Field(..., description="Technical CDS DDL source name.")
    source: str = Field(..., description="Raw CDS source code of the DDL source.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class DdicDdlSourceReadResponse(ApiResponse[DdicDdlSourceReadOutput]):
    """Response model for reading one CDS DDL source."""


class DdicDdlSourceUpdateRequest(BaseModel):
    """Full CDS source used to replace the content of one DDL source."""

    source: str = Field(..., description="Full CDS DDL source to store in source/main.")


class DdicDdlSourceUpdateOutput(BaseModel):
    """Result of updating one CDS DDL source."""

    uri: str = Field(..., description="Repository object URI of the DDL source.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    name: str = Field(..., description="Technical CDS DDL source name.")
    transportNumber: str = Field("", description="Transport request number forwarded during the update when provided.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class DdicDdlSourceUpdateResponse(ApiResponse[DdicDdlSourceUpdateOutput]):
    """Response model for updating one CDS DDL source."""


class DdicDdlSourceLockOutput(BaseModel):
    """Lock metadata returned for one CDS DDL source."""

    uri: str = Field(..., description="Repository object URI of the DDL source.")
    name: str = Field(..., description="Technical CDS DDL source name.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the DDL source.")
    corrnr: str = Field("", description="Transport request number returned by SAP when present.")
    corruser: str = Field("", description="Transport owner returned by SAP when present.")
    corrtext: str = Field("", description="Transport description returned by SAP when present.")
    isLocal: bool = Field(..., description="Whether SAP reports the lock as local.")


class DdicDdlSourceLockResponse(ApiResponse[DdicDdlSourceLockOutput]):
    """Response model for locking or unlocking one CDS DDL source."""


def _normalize_ddl_source_name(name: str) -> str:
    """Normalize one CDS DDL source name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _ddl_source_object_uri(name: str) -> str:
    """Return the repository object URI of one CDS DDL source."""
    normalized_name = _normalize_ddl_source_name(name)
    return f"{DDL_SOURCES_COLLECTION_URI}/{normalized_name.lower()}"


def _ddl_source_source_uri(name: str) -> str:
    """Return the source URI of one CDS DDL source."""
    return f"{_ddl_source_object_uri(name)}/source/main"


def _parse_bool(value) -> bool:
    """Parse boolean values returned by ADT XML payloads."""
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "x")


def _build_ddl_source_create_payload(
    name: str,
    description: str,
    package_name: str,
    responsible: str,
    language: str,
    master_system: str = "",
) -> str:
    """Build the ADT XML payload required to create one CDS DDL source."""
    root: dict = {
        "@xmlns:adtcore": "http://www.sap.com/adt/core",
        "@xmlns:ddl": "http://www.sap.com/adt/ddic/ddlsources",
        "@adtcore:description": description,
        "@adtcore:language": language,
        "@adtcore:name": name,
        "@adtcore:type": DDL_SOURCE_OBJECT_TYPE,
        "@adtcore:masterLanguage": language,
        "@adtcore:responsible": responsible,
        "adtcore:packageRef": {
            "@adtcore:name": package_name
        }
    }
    if master_system:
        root["@adtcore:masterSystem"] = master_system
    return xmltodict.unparse({"ddl:ddlSource": root}, pretty=False)


def call_ddic_ddl_source_lock(systemId: str, name: str) -> DdicDdlSourceLockResponse:
    """Lock one CDS DDL source through the ADT lock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return DdicDdlSourceLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock the DDL source because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_ddl_source_name(name)
        object_uri = _ddl_source_object_uri(normalized_name)
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
            return DdicDdlSourceLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the DDL source lock request: {response.text}",
                "data": None
            })

        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the DDL source.")

        return DdicDdlSourceLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "DDL source locked successfully.",
            "data": DdicDdlSourceLockOutput(
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
        return DdicDdlSourceLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DdicDdlSourceLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking the DDL source: {str(exc)}",
            "data": None,
        })


def call_ddic_ddl_source_unlock(systemId: str, name: str, lockHandle: str) -> DdicDdlSourceLockResponse:
    """Unlock one CDS DDL source through the ADT unlock action."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return DdicDdlSourceLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock the DDL source because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_ddl_source_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        object_uri = _ddl_source_object_uri(normalized_name)
        system_config = get_system_config(systemId)
        headers = build_adt_headers(sessionType="stateful")
        response = get_session(systemId).post(
            f"{system_config.server}{object_uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers=headers,
        )

        if response.status_code != 200:
            return DdicDdlSourceLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the DDL source unlock request: {response.text}",
                "data": None
            })

        return DdicDdlSourceLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "DDL source unlocked successfully.",
            "data": DdicDdlSourceLockOutput(
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
        return DdicDdlSourceLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DdicDdlSourceLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking the DDL source: {str(exc)}",
            "data": None,
        })


def call_ddic_ddl_source_create(
    systemId: str,
    name: str,
    description: str,
    packageName: str = "$TMP",
    transportNumber: str = "",
    responsible: str = "",
    language: str = "",
) -> DdicDdlSourceCreateResponse:
    """Create one CDS DDL source through the ADT DDL sources collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return DdicDdlSourceCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the DDL source because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_ddl_source_name(name)
        system_config = get_system_config(systemId)
        effective_language = str(language or "").strip() or system_config.language
        effective_responsible = str(responsible or "").strip() or system_config.user

        headers = {
            "Content-Type": "application/vnd.sap.adt.ddlSource+xml",
            "Accept": "application/vnd.sap.adt.ddlSource.v2+xml, application/vnd.sap.adt.ddlSource+xml",
        }
        if str(transportNumber or "").strip():
            headers["X-sap-adt-corrnr"] = str(transportNumber).strip()

        payload = _build_ddl_source_create_payload(
            name=normalized_name,
            description=description,
            package_name=packageName,
            responsible=effective_responsible,
            language=effective_language,
            master_system=system_config.id,
        )
        response = get_session(systemId).post(
            f"{system_config.server}{DDL_SOURCES_COLLECTION_URI}",
            headers=headers,
            data=payload.encode("utf-8"),
        )

        if response.status_code != 201:
            return DdicDdlSourceCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the DDL source creation request: {response.text}",
                "data": None
            })

        return DdicDdlSourceCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "DDL source created successfully.",
            "data": DdicDdlSourceCreateOutput(
                uri=_ddl_source_object_uri(normalized_name),
                sourceUri=_ddl_source_source_uri(normalized_name),
                name=normalized_name,
                packageName=packageName,
                description=description,
                transportNumber=str(transportNumber or ""),
            )
        })
    except ValueError as exc:
        return DdicDdlSourceCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DdicDdlSourceCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the DDL source: {str(exc)}",
            "data": None,
        })


def call_ddic_ddl_source_read(systemId: str, name: str) -> DdicDdlSourceReadResponse:
    """Read the raw source code of one CDS DDL source."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return DdicDdlSourceReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the DDL source because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_ddl_source_name(name)
        source_uri = _ddl_source_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return DdicDdlSourceReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the DDL source read request: {response.text}",
                "data": None
            })

        return DdicDdlSourceReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "DDL source read successfully.",
            "data": DdicDdlSourceReadOutput(
                uri=_ddl_source_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                source=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return DdicDdlSourceReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DdicDdlSourceReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the DDL source: {str(exc)}",
            "data": None,
        })


def call_ddic_ddl_source_update(
    systemId: str,
    name: str,
    lockHandle: str,
    request: DdicDdlSourceUpdateRequest,
    transportNumber: str = "",
) -> DdicDdlSourceUpdateResponse:
    """Update the raw source code of one existing CDS DDL source."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return DdicDdlSourceUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the DDL source because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_ddl_source_name(name)
        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")
        source_uri = _ddl_source_source_uri(normalized_name)
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
            return DdicDdlSourceUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the DDL source update request: {response.text}",
                "data": None
            })

        return DdicDdlSourceUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "DDL source updated successfully.",
            "data": DdicDdlSourceUpdateOutput(
                uri=_ddl_source_object_uri(normalized_name),
                sourceUri=source_uri,
                name=normalized_name,
                transportNumber=str(transportNumber or ""),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return DdicDdlSourceUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DdicDdlSourceUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the DDL source: {str(exc)}",
            "data": None,
        })


def call_ddic_ddl_source_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one CDS DDL source using the generic ADT deletion endpoint."""
    try:
        return call_deletion_delete(systemId, _ddl_source_object_uri(name), transportNumber)
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })


def call_ddic_ddl_source_read_to_file(systemId: str, name: str, filePath: str) -> FileTransferResponse:
    """Download one CDS DDL source to a local file."""
    try:
        response = call_ddic_ddl_source_read(systemId, name)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the DDL source.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.source)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="DDL source downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the DDL source to file: {str(exc)}")


def call_ddic_ddl_source_write_from_file(systemId: str, name: str, filePath: str, transportNumber: str = "") -> FileTransferResponse:
    """Upload one CDS DDL source from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        lock_response = call_ddic_ddl_source_lock(systemId, name)
        if not lock_response.result or not lock_response.data:
            return build_file_transfer_error(
                lock_response.message or "Failed to lock the DDL source.",
                lock_response.httpCode or 500,
                lock_response.httpReason or "Internal Server Error",
            )

        try:
            response = call_ddic_ddl_source_update(
                systemId,
                name,
                lock_response.data.lockHandle,
                DdicDdlSourceUpdateRequest(source=content),
                transportNumber,
            )
        finally:
            call_ddic_ddl_source_unlock(systemId, name, lock_response.data.lockHandle)

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the DDL source from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="DDL source uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the DDL source from file: {str(exc)}")
