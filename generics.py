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
