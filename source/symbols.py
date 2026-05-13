from pydantic import BaseModel, Field
from urllib.parse import quote

from configuration import get_session, get_system_config
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file
from connection.connection import ensure_login


TEXT_SYMBOLS_CONTENT_TYPE = "application/vnd.sap.adt.textelements.symbols.v1"


class SourceSymbolsReadOutput(BaseModel):
    """Raw text symbols returned for one ABAP source object."""

    uri: str = Field(..., description="Text symbols URI that was read.")
    objectName: str = Field(..., description="Technical name of the owning source object.")
    content: str = Field(..., description="Raw text symbols content.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class SourceSymbolsReadResponse(ApiResponse[SourceSymbolsReadOutput]):
    """Response model for reading one text symbols resource."""


class SourceSymbolsUpdateRequest(BaseModel):
    """Raw text symbols content used to update one existing text symbols resource."""

    content: str = Field(..., description="Full text symbols content to store in the symbols resource.")


class SourceSymbolsUpdateOutput(BaseModel):
    """Result of updating one text symbols resource."""

    uri: str = Field(..., description="Text symbols URI that was updated.")
    objectName: str = Field(..., description="Technical name of the owning source object.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class SourceSymbolsUpdateResponse(ApiResponse[SourceSymbolsUpdateOutput]):
    """Response model for updating one text symbols resource."""


class SourceSymbolsLockOutput(BaseModel):
    """Lock metadata returned for one text symbols resource."""

    uri: str = Field(..., description="Text symbols URI that was locked.")
    objectName: str = Field(..., description="Technical name of the owning source object.")
    lockHandle: str = Field(..., description="ADT lock handle required to update and unlock the text symbols resource.")


class SourceSymbolsLockResponse(ApiResponse[SourceSymbolsLockOutput]):
    """Response model for locking or unlocking one text symbols resource."""


def call_source_symbols_lock(systemId: str, symbolsUri: str, objectName: str) -> SourceSymbolsLockResponse:
    """Lock one ADT text symbols resource."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return SourceSymbolsLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot lock text symbols because no SAP session is available: {error_msg}",
                "data": None
            })

        system_config = get_system_config(systemId)
        response = get_session(systemId).post(
            f"{system_config.server}{symbolsUri}?_action=LOCK&accessMode=MODIFY",
            headers={
                "X-sap-adt-sessiontype": "stateful",
                "Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9",
            },
        )

        if response.status_code != 200:
            return SourceSymbolsLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the text symbols lock request: {response.text}",
                "data": None
            })

        import xmltodict
        parsed = xmltodict.parse(response.text)
        data = (((parsed.get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
        lock_handle = str(data.get("LOCK_HANDLE", "") or "")
        if not lock_handle:
            raise ValueError("SAP did not return a lock handle for the text symbols resource.")

        return SourceSymbolsLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Text symbols locked successfully.",
            "data": SourceSymbolsLockOutput(
                uri=symbolsUri,
                objectName=str(objectName or "").strip().upper(),
                lockHandle=lock_handle,
            )
        })
    except ValueError as exc:
        return SourceSymbolsLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SourceSymbolsLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while locking text symbols: {str(exc)}",
            "data": None,
        })


def call_source_symbols_unlock(systemId: str, symbolsUri: str, objectName: str, lockHandle: str) -> SourceSymbolsLockResponse:
    """Unlock one ADT text symbols resource."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return SourceSymbolsLockResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot unlock text symbols because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        system_config = get_system_config(systemId)
        response = get_session(systemId).post(
            f"{system_config.server}{symbolsUri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
            headers={"X-sap-adt-sessiontype": "stateful"},
        )

        if response.status_code != 200:
            return SourceSymbolsLockResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the text symbols unlock request: {response.text}",
                "data": None
            })

        return SourceSymbolsLockResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Text symbols unlocked successfully.",
            "data": SourceSymbolsLockOutput(
                uri=symbolsUri,
                objectName=str(objectName or "").strip().upper(),
                lockHandle=normalized_lock_handle,
            )
        })
    except ValueError as exc:
        return SourceSymbolsLockResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SourceSymbolsLockResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while unlocking text symbols: {str(exc)}",
            "data": None,
        })


def call_source_symbols_read(systemId: str, symbolsUri: str, objectName: str) -> SourceSymbolsReadResponse:
    """Read one ADT text symbols resource."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return SourceSymbolsReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read text symbols because no SAP session is available: {error_msg}",
                "data": None
            })

        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{symbolsUri}",
            headers={"Accept": TEXT_SYMBOLS_CONTENT_TYPE, "Cache-Control": "no-cache"},
        )

        if response.status_code != 200:
            return SourceSymbolsReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the text symbols read request: {response.text}",
                "data": None
            })

        return SourceSymbolsReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Text symbols read successfully.",
            "data": SourceSymbolsReadOutput(
                uri=symbolsUri,
                objectName=str(objectName or "").strip().upper(),
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except Exception as exc:
        return SourceSymbolsReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading text symbols: {str(exc)}",
            "data": None,
        })


def call_source_symbols_update(systemId: str, symbolsUri: str, objectName: str, request: SourceSymbolsUpdateRequest, lockHandle: str) -> SourceSymbolsUpdateResponse:
    """Update one ADT text symbols resource."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return SourceSymbolsUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update text symbols because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_lock_handle = str(lockHandle or "").strip()
        if not normalized_lock_handle:
            raise ValueError("lockHandle is required.")

        system_config = get_system_config(systemId)
        response = get_session(systemId).put(
            f"{system_config.server}{symbolsUri}?lockHandle={quote(normalized_lock_handle, safe='')}",
            headers={"Content-Type": f"{TEXT_SYMBOLS_CONTENT_TYPE}; charset=UTF-8", "Accept": TEXT_SYMBOLS_CONTENT_TYPE},
            data=request.content.encode("utf-8"),
        )

        if response.status_code not in {200, 204}:
            return SourceSymbolsUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the text symbols update request: {response.text}",
                "data": None
            })

        return SourceSymbolsUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Text symbols updated successfully.",
            "data": SourceSymbolsUpdateOutput(
                uri=symbolsUri,
                objectName=str(objectName or "").strip().upper(),
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return SourceSymbolsUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return SourceSymbolsUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating text symbols: {str(exc)}",
            "data": None,
        })


def call_source_symbols_read_to_file(systemId: str, symbolsUri: str, objectName: str, filePath: str) -> FileTransferResponse:
    """Download one text symbols resource to a local file."""
    try:
        response = call_source_symbols_read(systemId, symbolsUri, objectName)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the text symbols.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.uri,
            mimeType=response.data.contentType or TEXT_SYMBOLS_CONTENT_TYPE,
            sizeBytes=size_bytes,
            message="Text symbols downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download text symbols to file: {str(exc)}")


def call_source_symbols_write_from_file(systemId: str, symbolsUri: str, objectName: str, filePath: str, lockHandle: str) -> FileTransferResponse:
    """Upload one text symbols resource from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        response = call_source_symbols_update(
            systemId=systemId,
            symbolsUri=symbolsUri,
            objectName=objectName,
            request=SourceSymbolsUpdateRequest(content=content),
            lockHandle=lockHandle,
        )

        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the text symbols from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.uri,
            mimeType=response.data.contentType or TEXT_SYMBOLS_CONTENT_TYPE,
            sizeBytes=size_bytes,
            message="Text symbols uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload text symbols from file: {str(exc)}")
