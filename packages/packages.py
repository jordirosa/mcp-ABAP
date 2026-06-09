import xmltodict

from pydantic import BaseModel, Field

from configuration import get_session, get_system_config
from connection.connection import ensure_login
from deletion.deletion import DeletionDeleteResponse, call_deletion_delete
from generics import ApiResponse


PACKAGES_COLLECTION_URI = "/sap/bc/adt/packages"
PACKAGE_OBJECT_TYPE = "DEVC/K"
PACKAGE_CONTENT_TYPE = "application/vnd.sap.adt.packages.v2+xml"
PACKAGE_ACCEPT = "application/vnd.sap.adt.packages.v2+xml, application/vnd.sap.adt.packages.v1+xml"


class PackageCreateRequest(BaseModel):
    """Metadata required to create one ABAP package through ADT."""

    name: str = Field(..., description="Technical package name to create.")
    description: str = Field(..., description="Short package description.")
    language: str = Field("", description="Master language of the new package. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")
    superPackageName: str = Field("", description="Optional super package name. Leave empty for a top-level package.")
    packageType: str = Field("development", description="Package type to send to ADT, usually development.")
    isEncapsulated: bool = Field(True, description="Whether the package should be created as encapsulated.")
    softwareComponent: str = Field("HOME", description="Software component assigned to the package.")
    transportLayer: str = Field("", description="Transport layer assigned to the package.")
    applicationComponent: str = Field("", description="Optional application component.")


class PackageUpdateRequest(BaseModel):
    """Metadata used to update one existing ABAP package through ADT."""

    description: str = Field(..., description="Short package description.")
    language: str = Field("", description="Master language of the package. Defaults to the configured SAP logon language when omitted.")
    responsible: str = Field("", description="Responsible SAP user. Defaults to the configured SAP user when omitted.")
    superPackageName: str = Field("", description="Optional super package name. Leave empty for a top-level package.")
    packageType: str = Field("development", description="Package type to send to ADT, usually development.")
    isEncapsulated: bool = Field(True, description="Whether the package should be treated as encapsulated.")
    softwareComponent: str = Field("HOME", description="Software component assigned to the package.")
    transportLayer: str = Field("", description="Transport layer assigned to the package.")
    applicationComponent: str = Field("", description="Optional application component.")


class PackageOutput(BaseModel):
    """Normalized metadata returned for one ABAP package."""

    uri: str = Field(..., description="Repository object URI of the package.")
    name: str = Field(..., description="Technical package name.")
    description: str = Field("", description="Short package description.")
    objectType: str = Field("", description="ADT object type of the package.")
    language: str = Field("", description="Language returned by SAP for the package.")
    responsible: str = Field("", description="Responsible SAP user returned by SAP.")
    superPackageName: str = Field("", description="Super package returned by SAP, if any.")
    packageType: str = Field("", description="Package type returned by SAP.")
    isEncapsulated: bool = Field(False, description="Whether SAP reports the package as encapsulated.")
    softwareComponent: str = Field("", description="Software component assigned to the package.")
    transportLayer: str = Field("", description="Transport layer assigned to the package.")
    applicationComponent: str = Field("", description="Application component assigned to the package.")
    contentType: str = Field("", description="HTTP content type returned by SAP.")


class PackageCreateResponse(ApiResponse[PackageOutput]):
    """Response model for creating one ABAP package."""


class PackageReadResponse(ApiResponse[PackageOutput]):
    """Response model for reading one ABAP package."""


class PackageUpdateResponse(ApiResponse[PackageOutput]):
    """Response model for updating one ABAP package."""


class PackageLockOutput(BaseModel):
    """Minimal lock metadata returned by ADT for one package."""

    lockHandle: str = Field(..., description="Lock handle returned by ADT.")


def _normalize_package_name(name: str) -> str:
    """Normalize one ABAP package name."""
    normalized = str(name or "").strip().upper()
    if not normalized:
        raise ValueError("name is required.")
    return normalized


def _package_object_uri(name: str) -> str:
    """Return the repository object URI of one ABAP package."""
    normalized_name = _normalize_package_name(name)
    return f"{PACKAGES_COLLECTION_URI}/{normalized_name.lower()}"


def _build_package_payload(
    systemId: str,
    *,
    name: str,
    description: str,
    language: str,
    responsible: str,
    superPackageName: str,
    packageType: str,
    isEncapsulated: bool,
    softwareComponent: str,
    transportLayer: str,
    applicationComponent: str,
) -> str:
    """Build the ADT XML payload required to create or update one ABAP package."""
    system_config = get_system_config(systemId)
    normalized_name = _normalize_package_name(name)
    normalized_language = str(language or "").strip() or system_config.language
    normalized_responsible = str(responsible or "").strip() or system_config.user
    normalized_super_package = str(superPackageName or "").strip().upper()

    payload = {
        "pak:package": {
            "@xmlns:adtcore": "http://www.sap.com/adt/core",
            "@xmlns:pak": "http://www.sap.com/adt/packages",
            "@adtcore:description": description,
            "@adtcore:language": normalized_language,
            "@adtcore:name": normalized_name,
            "@adtcore:type": PACKAGE_OBJECT_TYPE,
            "@adtcore:version": "active",
            "@adtcore:masterLanguage": normalized_language,
            "@adtcore:masterSystem": system_config.id,
            "@adtcore:responsible": normalized_responsible,
            "adtcore:packageRef": {
                "@adtcore:name": normalized_name
            },
            "pak:attributes": {
                "@pak:isEncapsulated": "true" if isEncapsulated else "false",
                "@pak:packageType": str(packageType or "development").strip() or "development",
            },
            "pak:superPackage": (
                {"@adtcore:name": normalized_super_package}
                if normalized_super_package
                else None
            ),
            "pak:applicationComponent": {
                "@pak:name": str(applicationComponent or "").strip()
            },
            "pak:transport": {
                "pak:softwareComponent": {
                    "@pak:name": str(softwareComponent or "HOME").strip() or "HOME"
                },
                "pak:transportLayer": {
                    "@pak:name": str(transportLayer or "").strip()
                }
            },
            "pak:translation": None,
            "pak:useAccesses": None,
            "pak:packageInterfaces": None,
            "pak:subPackages": None,
        }
    }

    return xmltodict.unparse(payload, pretty=False)


def _parse_package_response(response) -> PackageOutput:
    """Parse one ADT package response payload."""
    data_dict = xmltodict.parse(response.text)
    package_root = data_dict.get("pak:package", {}) or {}
    package_ref = package_root.get("adtcore:packageRef", {}) or {}
    attributes = package_root.get("pak:attributes", {}) or {}
    super_package = package_root.get("pak:superPackage", {}) or {}
    transport_root = package_root.get("pak:transport", {}) or {}
    software_component = transport_root.get("pak:softwareComponent", {}) or {}
    transport_layer = transport_root.get("pak:transportLayer", {}) or {}
    application_component = package_root.get("pak:applicationComponent", {}) or {}

    return PackageOutput(
        uri=str(package_ref.get("@adtcore:uri", "") or package_root.get("@adtcore:uri", "") or ""),
        name=str(package_root.get("@adtcore:name", "") or ""),
        description=str(package_root.get("@adtcore:description", "") or ""),
        objectType=str(package_root.get("@adtcore:type", "") or ""),
        language=str(package_root.get("@adtcore:language", "") or ""),
        responsible=str(package_root.get("@adtcore:responsible", "") or ""),
        superPackageName=str(super_package.get("@adtcore:name", "") or ""),
        packageType=str(attributes.get("@pak:packageType", "") or ""),
        isEncapsulated=str(attributes.get("@pak:isEncapsulated", "false")).lower() == "true",
        softwareComponent=str(software_component.get("@pak:name", "") or ""),
        transportLayer=str(transport_layer.get("@pak:name", "") or ""),
        applicationComponent=str(application_component.get("@pak:name", "") or ""),
        contentType=response.headers.get("Content-Type", ""),
    )


def _parse_package_lock_handle(response) -> str:
    """Extract the lock handle from one ADT package lock response."""
    data_dict = xmltodict.parse(response.text)
    data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {}) or {}
    return str(data_root.get("LOCK_HANDLE", "") or "")


def _call_package_lock(systemId: str, name: str) -> str:
    """Lock one ABAP package and return the lock handle."""
    normalized_name = _normalize_package_name(name)
    system_config = get_system_config(systemId)
    response = get_session(systemId).post(
        f"{system_config.server}{_package_object_uri(normalized_name)}",
        headers={
            "X-sap-adt-sessiontype": "stateful",
            "Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9",
        },
        params={"_action": "LOCK", "accessMode": "MODIFY"},
    )
    if response.status_code != 200:
        raise RuntimeError(f"ADT rejected the package lock request: {response.text}")

    lock_handle = _parse_package_lock_handle(response)
    if not lock_handle:
        raise RuntimeError("ADT did not return a lockHandle for the package.")
    return lock_handle


def _call_package_unlock(systemId: str, name: str, lockHandle: str) -> None:
    """Unlock one ABAP package."""
    normalized_name = _normalize_package_name(name)
    system_config = get_system_config(systemId)
    response = get_session(systemId).post(
        f"{system_config.server}{_package_object_uri(normalized_name)}",
        headers={"X-sap-adt-sessiontype": "stateful"},
        params={"_action": "UNLOCK", "lockHandle": lockHandle},
    )
    if response.status_code != 200:
        raise RuntimeError(f"ADT rejected the package unlock request: {response.text}")


def call_package_create(systemId: str, request: PackageCreateRequest, corrNr: str = "") -> PackageCreateResponse:
    """Create one ABAP package through the ADT packages collection endpoint."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return PackageCreateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot create the package because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_package_name(request.name)
        system_config = get_system_config(systemId)
        normalized_corrnr = str(corrNr or "").strip().upper()
        url = f"{system_config.server}{PACKAGES_COLLECTION_URI}"
        params = {}
        if normalized_corrnr:
            params["corrNr"] = normalized_corrnr

        response = get_session(systemId).post(
            url,
            headers={
                "Content-Type": PACKAGE_CONTENT_TYPE,
                "Accept": PACKAGE_ACCEPT,
            },
            params=params,
            data=_build_package_payload(
                systemId,
                name=normalized_name,
                description=request.description,
                language=request.language,
                responsible=request.responsible,
                superPackageName=request.superPackageName,
                packageType=request.packageType,
                isEncapsulated=request.isEncapsulated,
                softwareComponent=request.softwareComponent,
                transportLayer=request.transportLayer,
                applicationComponent=request.applicationComponent,
            ).encode("utf-8"),
        )

        if response.status_code not in {200, 201}:
            return PackageCreateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the package creation request: {response.text}",
                "data": None
            })

        output = _parse_package_response(response)
        if not output.uri:
            output.uri = _package_object_uri(normalized_name)
        return PackageCreateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Package created successfully.",
            "data": output
        })
    except ValueError as exc:
        return PackageCreateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return PackageCreateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while creating the package: {str(exc)}",
            "data": None,
        })


def call_package_read(systemId: str, name: str) -> PackageReadResponse:
    """Read one ABAP package through its ADT resource URI."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return PackageReadResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot read the package because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_package_name(name)
        system_config = get_system_config(systemId)
        response = get_session(systemId).get(
            f"{system_config.server}{_package_object_uri(normalized_name)}",
            headers={"Accept": PACKAGE_ACCEPT},
        )

        if response.status_code != 200:
            return PackageReadResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the package read request: {response.text}",
                "data": None
            })

        output = _parse_package_response(response)
        if not output.uri:
            output.uri = _package_object_uri(normalized_name)
        return PackageReadResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Package read successfully.",
            "data": output
        })
    except ValueError as exc:
        return PackageReadResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return PackageReadResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while reading the package: {str(exc)}",
            "data": None,
        })


def call_package_update(systemId: str, name: str, request: PackageUpdateRequest, corrNr: str = "") -> PackageUpdateResponse:
    """Update one ABAP package through its ADT resource URI."""
    try:
        is_logged_in, error_msg = ensure_login(systemId)
        if not is_logged_in:
            return PackageUpdateResponse.model_validate({
                "result": False,
                "httpCode": 401,
                "httpReason": "Unauthorized",
                "message": f"Cannot update the package because no SAP session is available: {error_msg}",
                "data": None
            })

        normalized_name = _normalize_package_name(name)
        system_config = get_system_config(systemId)
        normalized_corrnr = str(corrNr or "").strip().upper()
        lock_handle = _call_package_lock(systemId, normalized_name)
        try:
            response = get_session(systemId).put(
                f"{system_config.server}{_package_object_uri(normalized_name)}",
                headers={
                    "Content-Type": PACKAGE_CONTENT_TYPE,
                    "Accept": PACKAGE_ACCEPT,
                },
                params={
                    "lockHandle": lock_handle,
                    **({"corrNr": normalized_corrnr} if normalized_corrnr else {}),
                },
                data=_build_package_payload(
                    systemId,
                    name=normalized_name,
                    description=request.description,
                    language=request.language,
                    responsible=request.responsible,
                    superPackageName=request.superPackageName,
                    packageType=request.packageType,
                    isEncapsulated=request.isEncapsulated,
                    softwareComponent=request.softwareComponent,
                    transportLayer=request.transportLayer,
                    applicationComponent=request.applicationComponent,
                ).encode("utf-8"),
            )
        finally:
            _call_package_unlock(systemId, normalized_name, lock_handle)

        if response.status_code not in {200, 204}:
            return PackageUpdateResponse.model_validate({
                "result": False,
                "httpCode": response.status_code,
                "httpReason": response.reason,
                "message": f"ADT rejected the package update request: {response.text}",
                "data": None
            })

        output = _parse_package_response(response) if response.text.strip() else PackageOutput(
            uri=_package_object_uri(normalized_name),
            name=normalized_name,
            description=request.description,
            objectType=PACKAGE_OBJECT_TYPE,
            language=request.language or get_system_config(systemId).language,
            responsible=request.responsible or get_system_config(systemId).user,
            superPackageName=str(request.superPackageName or "").strip().upper(),
            packageType=request.packageType,
            isEncapsulated=request.isEncapsulated,
            softwareComponent=request.softwareComponent,
            transportLayer=request.transportLayer,
            applicationComponent=request.applicationComponent,
            contentType=response.headers.get("Content-Type", ""),
        )
        return PackageUpdateResponse.model_validate({
            "result": True,
            "httpCode": response.status_code,
            "httpReason": response.reason,
            "message": "Package updated successfully.",
            "data": output
        })
    except ValueError as exc:
        return PackageUpdateResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return PackageUpdateResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while updating the package: {str(exc)}",
            "data": None,
        })


def call_package_delete(systemId: str, name: str, transportNumber: str = "") -> DeletionDeleteResponse:
    """Delete one ABAP package through the generic ADT deletion endpoint."""
    try:
        normalized_name = _normalize_package_name(name)
        return call_deletion_delete(
            systemId=systemId,
            objectUri=_package_object_uri(normalized_name),
            transportNumber=str(transportNumber or "").strip().upper(),
        )
    except ValueError as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return DeletionDeleteResponse.model_validate({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Unexpected error while deleting the package: {str(exc)}",
            "data": None,
        })
