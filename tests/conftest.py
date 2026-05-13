import pytest

from connection.connection import call_logout


@pytest.fixture
def sap_system_id() -> str:
    """Default SAP system used by integration tests."""
    return "A4H"


@pytest.fixture
def clean_sap_session(sap_system_id: str):
    """Ensure each integration test starts and ends without a leaked SAP session."""
    call_logout(sap_system_id)
    try:
        yield sap_system_id
    finally:
        call_logout(sap_system_id)
