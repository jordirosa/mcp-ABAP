from fastmcp import FastMCP
from pydantic import Field

from activation.activation import *
from configuration import *
from connection.connection import *
from cts.cts import *
from deletion.deletion import *
from ddic.db.settings import *
from ddic.dataelements.dataelements import *
from ddic.domains.domains import *
from ddic.tables.tables import *
from info_repository.info_repository import *

mcp = FastMCP(name="ABAP Tools - MCP Server", version="1.0.0")
print("FastMCP server object created.")

# region Systems
@mcp.tool()
def sap_systems_list() -> SapSystemListResponse:
    """List the SAP systems configured in the MCP server, including their ids, names, and environment types."""
    return call_sap_systems_list()
# endregion

#region Login/Logout
@mcp.tool()
def login(
    systemId: str = Field(..., description="Identifier of the configured SAP system to log in to. Use sap_systems_list first if you need to discover the available systems.")
) -> LoginResponse:
    """Open an authenticated ADT session for one configured SAP system and fetch its CSRF token.

    Call this before using tools that read or change SAP objects in that system."""
    return call_login(systemId)

@mcp.tool()
def logout(
    systemId: str = Field(..., description="Identifier of the configured SAP system whose session should be closed.")
) -> LogoutResponse:
    """Close the SAP session for one configured system and clear its stored CSRF token."""
    return call_logout(systemId)
#endregion

# region Info Repository
@mcp.tool()
def info_repository_search(systemId: str = Field(..., description="Identifier of the configured SAP system to query."),
           searchTerm: str = Field(..., description="Search pattern for the SAP repository information system. Supports wildcards such as '*' and can match object names or descriptions."),
           objectType: str = Field("", description="Optional 4-character SAP object type filter such as PROG, CLAS, FUGR, TABL, DTEL, DOMA, INTF, or DDLS.")) -> InfoRepositorySearchResponse:
    """Search the SAP repository information system of one configured SAP system for development objects."""
    return call_info_repository_search(systemId, searchTerm, objectType=objectType)
# endregion

# region Activation
@mcp.tool()
def activation_activate(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the activation should run."),
    request: ActivationActivateRequest = Field(..., description="One or more ADT object references to activate. Use ADT URIs such as /sap/bc/adt/ddic/domains/<name>, /sap/bc/adt/ddic/dataelements/<name>, /sap/bc/adt/ddic/tables/<name>, or /sap/bc/adt/ddic/db/settings/<table>.")
) -> ActivationActivateResponse:
    """Activate one or more ADT objects in one configured SAP system through the generic activation endpoint."""
    return call_activation_activate(systemId, request)
# endregion

# region CTS
@mcp.tool()
def cts_transport_check(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the CTS check should run."),
    objectUri: str = Field(..., description="ADT URI of the object that may need a transport request."),
    packageName: str = Field(..., description="Package that will own or change the object."),
    operation: str = Field("I", description="CTS operation code to check, such as I for create or U for update."),
    superPackage: str = Field("", description="Optional super package name when the CTS check depends on package hierarchy."),
    recordChanges: str = Field("", description="Optional CTS record-changes flag to forward to the SAP check.")
) -> CtsTransportCheckResponse:
    """Check whether working with an object in a package requires a transport request in one configured SAP system."""
    return call_cts_transport_check(
        systemId=systemId,
        objectUri=objectUri,
        packageName=packageName,
        operation=operation,
        superPackage=superPackage,
        recordChanges=recordChanges
    )


@mcp.tool()
def cts_transport_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the transport request should be created."),
    packageName: str = Field(..., description="Package for which the transport request will be created."),
    requestText: str = Field(..., description="Short description of the transport request."),
    objectUri: str = Field(..., description="ADT URI of the object that will be referenced by the transport request."),
    operation: str = Field("I", description="CTS operation code for the referenced change, such as I for create or U for update.")
) -> CtsTransportCreateResponse:
    """Create a transport request in one configured SAP system for a package and object reference."""
    return call_cts_transport_create(
        systemId=systemId,
        packageName=packageName,
        requestText=requestText,
        objectUri=objectUri,
        operation=operation
    )
# endregion

# region DDIC Table DB Settings
@mcp.tool()
def ddic_table_db_settings_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the table database settings should be read."),
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings should be read.")
) -> DdicTableDbSettingsReadResponse:
    """Read the database settings of a DDIC table in one configured SAP system."""
    return call_ddic_table_db_settings_read(systemId, tableName)


@mcp.tool()
def ddic_table_db_settings_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the table database settings will be updated."),
    tableName: str = Field(..., description="Technical name of the DDIC table whose database settings will be updated."),
    request: DdicTableDbSettingsUpdateRequest = Field(..., description="Set only the database settings attributes that should change. Omitted fields are kept as they are."),
    transportNumber: str = Field("", description="Transport request number to use when updating database settings in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicTableDbSettingsUpdateResponse:
    """Update the database settings of a DDIC table in one configured SAP system. The tool locks the settings object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_table_db_settings_lock(systemId, tableName)
    if not lock_response.result or not lock_response.data:
        return DdicTableDbSettingsUpdateResponse.parse_obj({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock table database settings",
            "data": None
        })

    try:
        return call_ddic_table_db_settings_update(
            systemId=systemId,
            tableName=tableName,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_table_db_settings_unlock(systemId, tableName, lock_response.data.lockHandle)
# endregion

# region DDIC Tables
@mcp.tool()
def ddic_table_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be created."),
    name: str = Field(..., description="Technical name of the DDIC table to create."),
    description: str = Field(..., description="Short description of the DDIC table."),
    packageName: str = Field("$TMP", description="Package where the DDIC table will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC table in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC table metadata. If omitted, the configured SAP language is used.")
) -> DdicTableCreateResponse:
    """Create a DDIC table in one configured SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_table_create(
        systemId=systemId,
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_table_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table source should be read."),
    name: str = Field(..., description="Technical name of the DDIC table to read.")
) -> DdicTableReadResponse:
    """Read the current source/main content of a DDIC table in one configured SAP system."""
    return call_ddic_table_read(systemId, name)


@mcp.tool()
def ddic_table_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be updated."),
    name: str = Field(..., description="Technical name of the DDIC table to update."),
    request: DdicTableUpdateRequest = Field(..., description="Replacement source for the DDIC table. Provide the full source/main content to store."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC table in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicTableUpdateResponse:
    """Update the source/main content of a DDIC table in one configured SAP system. The tool locks the object, writes the new source, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_table_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return DdicTableUpdateResponse.parse_obj({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock table",
            "data": None
        })

    try:
        return call_ddic_table_update(
            systemId=systemId,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_table_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_table_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC table will be deleted."),
    name: str = Field(..., description="Technical name of the DDIC table to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC table from one configured SAP system through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        systemId=systemId,
        objectUri=f"/sap/bc/adt/ddic/tables/{name.lower()}",
        transportNumber=transportNumber
    )
# endregion

# region DDIC Data Elements
@mcp.tool()
def ddic_dataelement_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be created."),
    name: str = Field(..., description="Technical name of the DDIC data element to create."),
    description: str = Field(..., description="Short description of the DDIC data element."),
    packageName: str = Field("$TMP", description="Package where the DDIC data element will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC data element in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC data element metadata. If omitted, the configured SAP language is used.")
) -> DdicDataElementCreateResponse:
    """Create a DDIC data element in one configured SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_dataelement_create(
        systemId=systemId,
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_dataelement_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element should be read."),
    name: str = Field(..., description="Technical name of the DDIC data element to read.")
) -> DdicDataElementReadResponse:
    """Read the metadata and technical settings of a DDIC data element in one configured SAP system."""
    return call_ddic_dataelement_read(systemId, name)


@mcp.tool()
def ddic_dataelement_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be updated."),
    name: str = Field(..., description="Technical name of the DDIC data element to update."),
    request: DdicDataElementUpdateRequest = Field(..., description="Set only the DDIC data element attributes that should change. Omitted fields are kept as they are."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC data element in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicDataElementUpdateResponse:
    """Update a DDIC data element in one configured SAP system. The tool locks the object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_dataelement_lock(systemId, name)
    if not lock_response.result or not lock_response.data:
        return DdicDataElementUpdateResponse.parse_obj({
            "result": False,
            "httpCode": lock_response.httpCode,
            "httpReason": lock_response.httpReason,
            "message": lock_response.message or "Failed to lock data element",
            "data": None
        })

    try:
        return call_ddic_dataelement_update(
            systemId=systemId,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_dataelement_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_dataelement_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC data element will be deleted."),
    name: str = Field(..., description="Technical name of the DDIC data element to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC data element from one configured SAP system through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        systemId=systemId,
        objectUri=f"/sap/bc/adt/ddic/dataelements/{name.lower()}",
        transportNumber=transportNumber
    )
# endregion

# region DDIC Domains
@mcp.tool()
def ddic_domain_create(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be created."),
    name: str = Field(..., description="Technical name of the DDIC domain to create."),
    description: str = Field(..., description="Short description of the DDIC domain."),
    packageName: str = Field("$TMP", description="Package where the DDIC domain will be created. Use $TMP for local objects."),
    transportNumber: str = Field("", description="Transport request number to use when creating the DDIC domain in a transportable package. Leave empty for local objects such as $TMP."),
    responsible: str = Field("", description="Responsible SAP user. If omitted, the configured SAP user is used."),
    language: str = Field("", description="Language key for the DDIC domain metadata. If omitted, the configured SAP language is used.")
) -> DdicDomainCreateResponse:
    """Create a DDIC domain in one configured SAP system. For transportable packages, provide the transport request number."""
    return call_ddic_domain_create(
        systemId=systemId,
        name=name,
        description=description,
        packageName=packageName,
        transportNumber=transportNumber,
        responsible=responsible,
        language=language
    )


@mcp.tool()
def ddic_domain_read(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain should be read."),
    name: str = Field(..., description="Technical name of the DDIC domain to read.")
) -> DdicDomainReadResponse:
    """Read the metadata and technical settings of a DDIC domain in one configured SAP system."""
    return call_ddic_domain_read(systemId, name)


@mcp.tool()
def ddic_domain_update(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be updated."),
    name: str = Field(..., description="Technical name of the DDIC domain to update."),
    request: DdicDomainUpdateRequest = Field(..., description="Set only the DDIC domain attributes that should change. Omitted fields are kept as they are."),
    transportNumber: str = Field("", description="Transport request number to use when updating a DDIC domain in a transportable package. Leave empty for local objects such as $TMP.")
) -> DdicDomainUpdateResponse:
    """Update a DDIC domain in one configured SAP system. The tool locks the object, applies the changes, and unlocks it automatically. For transportable packages, provide the transport request number."""
    lock_response = call_ddic_domain_lock(systemId, name)
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
            systemId=systemId,
            name=name,
            lockHandle=lock_response.data.lockHandle,
            request=request,
            transportNumber=transportNumber
        )
    finally:
        call_ddic_domain_unlock(systemId, name, lock_response.data.lockHandle)


@mcp.tool()
def ddic_domain_delete(
    systemId: str = Field(..., description="Identifier of the configured SAP system where the DDIC domain will be deleted."),
    name: str = Field(..., description="Technical name of the DDIC domain to delete."),
    transportNumber: str = Field("", description="Optional transport request number to use for the deletion.")
) -> DeletionDeleteResponse:
    """Delete a DDIC domain from one configured SAP system through the generic ADT deletion endpoint."""
    return call_deletion_delete(
        systemId=systemId,
        objectUri=f"/sap/bc/adt/ddic/domains/{name.lower()}",
        transportNumber=transportNumber
    )
# endregion

if __name__ == "__main__":
    print("\n--- Initiating FastMCP server through __main__ ---")
    mcp.run()
