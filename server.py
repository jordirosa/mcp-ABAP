from fastmcp import FastMCP
from pydantic import Field

from connection.connection import *
from cts.cts import *
from deletion.deletion import *
from ddic.domains.domains import *
from info_repository.info_repository import *

mcp = FastMCP(name="ABAP Tools - MCP Server", version="1.0.0")
print("FastMCP server object created.")

#region Login/Logout
@mcp.tool()
def login() -> LoginResponse:
    """Open an authenticated ADT session against the SAP system and fetch the CSRF token.

    Call this before using tools that read or change SAP objects."""
    return call_login()

@mcp.tool()
def logout() -> LogoutResponse:
    """Close the current SAP session and clear the stored CSRF token."""
    return call_logout()
#endregion

# region Info Repository
@mcp.tool()
def info_repository_search(searchTerm: str = Field(..., description="Search pattern for the SAP repository information system. Supports wildcards such as '*' and can match object names or descriptions."),
           objectType: str = Field("", description="Optional 4-character SAP object type filter such as PROG, CLAS, FUGR, TABL, DTEL, DOMA, INTF, or DDLS.")) -> InfoRepositorySearchResponse:
    """Search the SAP repository information system for development objects."""
    return call_info_repository_search(searchTerm, objectType=objectType)
# endregion

# region CTS
@mcp.tool()
def cts_transport_check(
    objectUri: str = Field(..., description="ADT URI of the object that may need a transport request."),
    packageName: str = Field(..., description="Package that will own or change the object."),
    operation: str = Field("I", description="CTS operation code to check, such as I for create or U for update."),
    superPackage: str = Field("", description="Optional super package name when the CTS check depends on package hierarchy."),
    recordChanges: str = Field("", description="Optional CTS record-changes flag to forward to the SAP check.")
) -> CtsTransportCheckResponse:
    """Check whether working with an object in a package requires a transport request."""
    return call_cts_transport_check(
        objectUri=objectUri,
        packageName=packageName,
        operation=operation,
        superPackage=superPackage,
        recordChanges=recordChanges
    )


@mcp.tool()
def cts_transport_create(
    packageName: str = Field(..., description="Package for which the transport request will be created."),
    requestText: str = Field(..., description="Short description of the transport request."),
    objectUri: str = Field(..., description="ADT URI of the object that will be referenced by the transport request."),
    operation: str = Field("I", description="CTS operation code for the referenced change, such as I for create or U for update.")
) -> CtsTransportCreateResponse:
    """Create a transport request for a package and object reference."""
    return call_cts_transport_create(
        packageName=packageName,
        requestText=requestText,
        objectUri=objectUri,
        operation=operation
    )
# endregion

# region DDIC Domains
@mcp.tool()
def ddic_domain_create(
    name: str = Field(..., description="Technical name of the DDIC domain to create."),
    description: str = Field(..., description="Short description of the DDIC domain."),
    packageName: str = Field("$TMP", description="Package where the DDIC domain will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC domain in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC domain metadata. If omitted, the configured SAP language is used.")
) -> DdicDomainCreateResponse:
    """Create a DDIC domain in the SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_domain_create(
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_domain_read(
    name: str = Field(..., description="Technical name of the DDIC domain to read.")
) -> DdicDomainReadResponse:
    """Read the metadata and technical settings of a DDIC domain."""
    return call_ddic_domain_read(name)


@mcp.tool()
def ddic_domain_update(
    name: str = Field(..., description="Technical name of the DDIC domain to update."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC domain in a transportable package. Leave empty for local objects such as $TMP."),
    request: DdicDomainUpdateRequest = Field(..., description="Set only the DDIC domain attributes that should change. Omitted fields are kept as they are.")
) -> DdicDomainUpdateResponse:
    """Update a DDIC domain. The tool locks the object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_domain_lock(name)
    if not lock_response.result or not lock_response.data:
        return DdicDomainUpdateResponse.parse_obj({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock domain",
            "data": None
        })

    try:
        return call_ddic_domain_update(
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_domain_unlock(name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_domain_delete(
    name: str = Field(..., description="Technical name of the DDIC domain to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC domain through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        objectUri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
        transportNumber=transportNumber
    )
# endregion

if __name__ == "__main__":
    print("\n--- Initiating FastMCP server through __main__ ---")
    mcp.run()
