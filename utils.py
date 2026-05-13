from pathlib import Path

from generics import FileTransferOutput, FileTransferResponse


def ensure_absolute_file_path(filePath: str) -> Path:
    """Validate that the provided path is absolute and return it as Path."""
    path = Path(filePath)
    if not path.is_absolute():
        raise ValueError("The file path must be absolute.")
    return path


def write_text_file(filePath: str, content: str) -> int:
    """Write UTF-8 text content to an absolute path and return its size in bytes."""
    path = ensure_absolute_file_path(filePath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def read_text_file(filePath: str) -> tuple[str, int]:
    """Read UTF-8 text content from an absolute path and return content plus size in bytes."""
    path = ensure_absolute_file_path(filePath)
    content = path.read_text(encoding="utf-8")
    return content, len(content.encode("utf-8"))


def build_file_transfer_response(filePath: str, uri: str, mimeType: str, sizeBytes: int, message: str) -> FileTransferResponse:
    """Build a successful file transfer response."""
    return FileTransferResponse.model_validate({
        "result": True,
        "httpCode": 200,
        "httpReason": "OK",
        "message": message,
        "data": FileTransferOutput(
            filePath=filePath,
            uri=uri,
            mimeType=mimeType,
            sizeBytes=sizeBytes
        )
    })


def build_file_transfer_error(message: str, httpCode: int = 500, httpReason: str = "Internal Server Error") -> FileTransferResponse:
    """Build a failed file transfer response."""
    return FileTransferResponse.model_validate({
        "result": False,
        "httpCode": httpCode,
        "httpReason": httpReason,
        "message": message,
        "data": None
    })
