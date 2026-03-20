from typing import Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Generic response wrapper for MCP tools."""

    result: bool = Field(..., description="Indicates whether the operation succeeded.")
    httpCode: int | None = Field(None, description="HTTP status code of the response.")
    httpReason: str | None = Field(None, description="HTTP status text of the response.")
    message: str | None = Field(None, description="Optional informational or error message.")
    data: T | None = Field(None, description="Payload returned when the operation succeeds.")


class FileTransferOutput(BaseModel):
    """Metadata returned by tools that move raw ADT content to or from local files."""

    filePath: str = Field(..., description="Absolute local file path used by the tool.")
    uri: str = Field(..., description="ADT URI of the SAP object or content resource involved in the transfer.")
    mimeType: str = Field(..., description="Content type used for the transferred raw content.")
    sizeBytes: int = Field(..., description="Number of bytes written to or read from the local file.")


class FileTransferResponse(ApiResponse[FileTransferOutput]):
    """Response model for local file transfer tools."""
