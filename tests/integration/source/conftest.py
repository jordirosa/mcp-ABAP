from datetime import datetime


def unique_source_name(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%H%M%S%f')[-8:]}"
