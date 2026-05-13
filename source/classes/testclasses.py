import xmltodict

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import ensure_login
from generics import ApiResponse, FileTransferResponse
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file
from source.classes.classes import _class_object_uri, _normalize_class_name, call_class_lock, call_class_unlock


CLASS_INCLUDE_CONTENT_TYPE = "application/vnd.sap.adt.oo.classincludes+xml"
TESTCLASSES_INCLUDE_NAME = "testclasses"


class ClassTestclassesCreateOutput(BaseModel):
    """Result of creating the testclasses include of one ABAP class."""

    uri: str = Field(..., description="Repository object URI of the created testclasses include.")
    sourceUri: str = Field(..., description="Source URI of the created testclasses include.")
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include.")
    includeType: str = Field(..., description="Include subtype returned by ADT, usually testclasses.")


class ClassTestclassesCreateResponse(ApiResponse[ClassTestclassesCreateOutput]):
    """Response model for creating one class testclasses include."""


class ClassTestclassesReadOutput(BaseModel):
    """Raw source code returned for one class testclasses include."""

    uri: str = Field(..., description="Repository object URI of the testclasses include.")
    sourceUri: str = Field(..., description="Source URI used to read the testclasses include.")
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include.")
    content: str = Field(..., description="Raw ABAP source code of the testclasses include.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class ClassTestclassesReadResponse(ApiResponse[ClassTestclassesReadOutput]):
    """Response model for reading one class testclasses include."""


class ClassTestclassesUpdateRequest(BaseModel):
    """Raw ABAP source code used to update one class testclasses include."""

    source: str = Field(..., description="Full ABAP source code to store in the testclasses include.")


class ClassTestclassesUpdateOutput(BaseModel):
    """Result of updating one class testclasses include."""

    uri: str = Field(..., description="Repository object URI of the testclasses include.")
    sourceUri: str = Field(..., description="Source URI that was updated.")
    className: str = Field(..., description="Technical ABAP class name that owns the testclasses include.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class ClassTestclassesUpdateResponse(ApiResponse[ClassTestclassesUpdateOutput]):
    """Response model for updating one class testclasses include."""


def _class_testclasses_object_uri(className: str) -> str:
    """Return the repository object URI of the testclasses include of one ABAP class."""
    normalized_name = _normalize_class_name(className)
    return f"{_class_object_uri(normalized_name)}/includes/{TESTCLASSES_INCLUDE_NAME}"


def _class_testclasses_collection_uri(className: str) -> str:
    """Return the collection URI that owns class includes."""
    normalized_name = _normalize_class_name(className)
    return f"{_class_object_uri(normalized_name)}/includes"


def _class_testclasses_source_uri(className: str) -> str:
    """Return the text resource URI of the testclasses include of one ABAP class."""
    return _class_testclasses_object_uri(className)


def _build_testclasses_create_payload() -> str:
    """Build the ADT XML payload required to create the testclasses include."""
    payload = {
        "class:abapClassInclude": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:class": "http://www.sap.com/adt/oo/classes",
            "@adtcore:name": "dummy",
            "@class:includeType": TESTCLASSES_INCLUDE_NAME,
        }
    }
    return xmltodict.unparse(payload, pretty=False)


def call_class_testclasses_create(systemId: str, className: str) -> ClassTestclassesCreateResponse:
    """Create the testclasses include of one ABAP class."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassTestclassesCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the class testclasses include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(className)
        lock_response = call_class_lock(systemId, normalized_name)
        if not lock_response.result or not lock_response.data:
            return ClassTestclassesCreateResponse.model_validate({
                "result": False,
                "httpCode": lock_response.httpCode,
                "httpReason": lock_response.httpReason,
                "message": lock_response.message or "Failed to lock the class.",
                "data": None
            })

        try:
            system_config = get_system_config(systemId)
            response = get_session(systemId).post(
                f"{system_config.server}{_class_testclasses_collection_uri(normalized_name)}?lockHandle={lock_response.data.lockHandle}",
                headers={"Content-Type": CLASS_INCLUDE_CONTENT_TYPE, "Accept": "application/xml"},
                data=_build_testclasses_create_payload().encode("utf-8"),
            )
        finally:
            call_class_unlock(systemId, normalized_name, lock_response.data.lockHandle)

        if response.status_code not in {200, 201}:
            return ClassTestclassesCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class testclasses creation request: {response.text}",
                "data": None
            })

        location = response.headers.get("Location", "") or _class_testclasses_object_uri(normalized_name)
        return ClassTestclassesCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class testclasses include created successfully.",
            "data": ClassTestclassesCreateOutput(
                uri=location,
                sourceUri=location,
                className=normalized_name,
                includeType=TESTCLASSES_INCLUDE_NAME,
            )
        })
    except ValueError as exc:
        return ClassTestclassesCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassTestclassesCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the class testclasses include: {str(exc)}",
            "data": None,
        })


def call_class_testclasses_read(systemId: str, className: str) -> ClassTestclassesReadResponse:
    """Read the raw source code of the testclasses include of one ABAP class."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return ClassTestclassesReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the class testclasses include because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_class_name(className)
        source_uri = _class_testclasses_source_uri(normalized_name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{source_uri}",
            headers={"Accept": "text/plain"},
        )

        if response.status_code != 200:
            return ClassTestclassesReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class testclasses read request: {response.text}",
                "data": None
            })

        return ClassTestclassesReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class testclasses include read successfully.",
            "data": ClassTestclassesReadOutput(
                uri=_class_testclasses_object_uri(normalized_name),
                sourceUri=source_uri,
                className=normalized_name,
                content=response.text,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return ClassTestclassesReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassTestclassesReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the class testclasses include: {str(exc)}",
            "data": None,
        })


def call_class_testclasses_update(systemId: str, className: str, request: ClassTestclassesUpdateRequest) -> ClassTestclassesUpdateResponse:
    """Update the raw source code of the testclasses include of one ABAP class."""
    try:
        normalized_name = _normalize_class_name(className)
        lock_response = call_class_lock(systemId, normalized_name)
        if not lock_response.result or not lock_response.data:
            return ClassTestclassesUpdateResponse.model_validate({
                "result": False,
                "httpCode": lock_response.httpCode,
                "httpReason": lock_response.httpReason,
                "message": lock_response.message or "Failed to lock the class.",
                "data": None
            })

        try:
            system_config = get_system_config(systemId)
            source_uri = _class_testclasses_source_uri(normalized_name)
            response = get_session(systemId).put(
                f"{system_config.server}{source_uri}?lockHandle={lock_response.data.lockHandle}",
                headers={"Content-Type": "text/plain; charset=utf-8", "Accept": "text/plain"},
                data=request.source.encode("utf-8"),
            )
        finally:
            call_class_unlock(systemId, normalized_name, lock_response.data.lockHandle)

        if response.status_code not in {200, 204}:
            return ClassTestclassesUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the class testclasses update request: {response.text}",
                "data": None
            })

        return ClassTestclassesUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Class testclasses include updated successfully.",
            "data": ClassTestclassesUpdateOutput(
                uri=_class_testclasses_object_uri(normalized_name),
                sourceUri=_class_testclasses_source_uri(normalized_name),
                className=normalized_name,
                contentType=response.headers.get("Content-Type", ""),
            )
        })
    except ValueError as exc:
        return ClassTestclassesUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return ClassTestclassesUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the class testclasses include: {str(exc)}",
            "data": None,
        })

def call_class_testclasses_read_to_file(systemId: str, className: str, filePath: str) -> FileTransferResponse:
    """Download the testclasses include of one ABAP class to a local file."""
    try:
        response = call_class_testclasses_read(systemId, className)
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to read the class testclasses include.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        size_bytes = write_text_file(filePath, response.data.content)
        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Class testclasses include downloaded to local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to download the class testclasses include to file: {str(exc)}")


def call_class_testclasses_write_from_file(systemId: str, className: str, filePath: str) -> FileTransferResponse:
    """Upload the testclasses include of one ABAP class from a local file."""
    try:
        content, size_bytes = read_text_file(filePath)
        response = call_class_testclasses_update(systemId, className, ClassTestclassesUpdateRequest(source=content))
        if not response.result or not response.data:
            return build_file_transfer_error(
                response.message or "Failed to upload the class testclasses include from file.",
                response.httpCode or 500,
                response.httpReason or "Internal Server Error",
            )

        return build_file_transfer_response(
            filePath=filePath,
            uri=response.data.sourceUri,
            mimeType=response.data.contentType or "text/plain",
            sizeBytes=size_bytes,
            message="Class testclasses include uploaded from local file successfully.",
        )
    except ValueError as exc:
        return build_file_transfer_error(str(exc), 400, "Bad Request")
    except Exception as exc:
        return build_file_transfer_error(f"Failed to upload the class testclasses include from file: {str(exc)}")
