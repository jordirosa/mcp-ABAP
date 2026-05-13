from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from generics import ApiResponse
from connection.connection import build_adt_headers, ensure_login


# region DDIC Tables
class DdicTableOutput(BaseModel):
	"""Normalized DDIC table metadata returned by ADT."""
	uri: str = Field(..., description="ADT URI of the DDIC table object.")
	sourceUri: str = Field(default="", description="ADT URI of the table source content.")
	name: str = Field(..., description="Technical name of the DDIC table.")
	type: str = Field(..., description="ADT object type of the DDIC table.")
	description: str = Field(default="", description="Short description of the DDIC table.")
	language: str = Field(default="", description="Language key stored in the DDIC table metadata.")
	responsible: str = Field(default="", description="Responsible SAP user for the DDIC table.")
	packageName: str = Field(default="", description="Package that contains the DDIC table.")
	version: str = Field(default="", description="Version status reported by ADT, such as active or inactive.")
	createdAt: str = Field(default="", description="UTC timestamp when the DDIC table was created.")
	createdBy: str = Field(default="", description="SAP user who created the DDIC table.")
	changedAt: str = Field(default="", description="UTC timestamp of the latest DDIC table change.")
	changedBy: str = Field(default="", description="SAP user who last changed the DDIC table.")
	abapLanguageVersion: str = Field(default="", description="ABAP language version assigned to the DDIC table.")


class DdicTableSourceOutput(BaseModel):
	"""Normalized DDIC table source returned by ADT."""
	uri: str = Field(..., description="ADT URI of the table source content.")
	name: str = Field(..., description="Technical name of the DDIC table.")
	source: str = Field(..., description="Current source code of the DDIC table.")
	etag: str = Field(default="", description="ETag returned by ADT for the current source version.")
	lastModified: str = Field(default="", description="Last-Modified header returned by ADT for the current source version.")


class DdicTableCreateResponse(ApiResponse[DdicTableOutput]):
	"""Response model for DDIC table creation API call."""


class DdicTableReadResponse(ApiResponse[DdicTableSourceOutput]):
	"""Response model for DDIC table read API call."""


class DdicTableUpdateResponse(ApiResponse[DdicTableSourceOutput]):
	"""Response model for DDIC table update API call."""


class DdicTableUpdateRequest(BaseModel):
	"""Payload used to replace the full source of a DDIC table."""
	source: str = Field(..., description="Full ABAP CDS-style source of the DDIC table to store in source/main.")


class DdicTableLockOutput(BaseModel):
	"""Lock metadata returned by the internal DDIC table lock operation."""
	lockHandle: str = Field(..., description="Lock handle returned by ADT.")
	corrNr: str = Field(default="", description="Transport request number proposed by SAP for the lock, when applicable.")
	corrUser: str = Field(default="", description="Owner of the transport request.")
	corrText: str = Field(default="", description="Description of the transport request.")
	isLocal: bool = Field(default=False, description="Whether the locked object is local.")
	isLinkUp: bool = Field(default=False, description="Whether SAP reports a link-up for the lock.")
	modificationSupport: str = Field(default="", description="Modification support information returned by ADT.")
	scopeMessages: str = Field(default="", description="Additional scope messages returned by ADT.")


class DdicTableLockResponse(ApiResponse[DdicTableLockOutput]):
	"""Response model for DDIC table lock API call."""


class DdicTableUnlockResponse(ApiResponse[BaseModel]):
	"""Response model for DDIC table unlock API call."""


def _parse_bool(value) -> bool:
	"""Parse boolean values returned by ADT XML payloads."""
	if isinstance(value, bool):
		return value
	return str(value).lower() in ("true", "x")


def _build_table_create_payload(
	name: str,
	description: str,
	package_name: str,
	responsible: str,
	language: str,
) -> str:
	"""Build XML payload for ADT table creation."""
	payload = {
		"blue:blueSource": {
			"@xmlns:adtcore": "http://www.sap.com/adt/core",
			"@xmlns:blue": "http://www.sap.com/wbobj/blue",
			"@adtcore:description": description,
			"@adtcore:language": language,
			"@adtcore:name": name,
			"@adtcore:type": "TABL/DT",
			"@adtcore:masterLanguage": language,
			"@adtcore:responsible": responsible,
			"adtcore:packageRef": {
				"@adtcore:name": package_name
			}
		}
	}
	return xmltodict.unparse(payload, pretty=False)


def _parse_ddic_table_create_response(response) -> DdicTableOutput:
	"""Parse XML response from DDIC table creation API."""
	data_dict = xmltodict.parse(response.text)
	root = data_dict.get("blue:blueSource", {})
	package_ref = root.get("adtcore:packageRef", {}) or {}
	source_uri = root.get("@abapsource:sourceUri", "") or ""
	if source_uri.startswith("./"):
		source_uri = f"/sap/bc/adt/ddic/tables/{root.get('@adtcore:name', '').lower()}/{source_uri[2:]}"

	return DdicTableOutput(
		uri=response.headers.get("Location", "") or f"/sap/bc/adt/ddic/tables/{root.get('@adtcore:name', '').lower()}",
		sourceUri=source_uri,
		name=root.get("@adtcore:name", ""),
		type=root.get("@adtcore:type", ""),
		description=root.get("@adtcore:description", ""),
		language=root.get("@adtcore:language", ""),
		responsible=root.get("@adtcore:responsible", ""),
		packageName=package_ref.get("@adtcore:name", ""),
		version=root.get("@adtcore:version", ""),
		createdAt=root.get("@adtcore:createdAt", ""),
		createdBy=root.get("@adtcore:createdBy", ""),
		changedAt=root.get("@adtcore:changedAt", ""),
		changedBy=root.get("@adtcore:changedBy", ""),
		abapLanguageVersion=root.get("@adtcore:abapLanguageVersion", ""),
	)


def _parse_ddic_table_source_response(systemId: str, name: str, response) -> DdicTableSourceOutput:
	"""Parse text response from DDIC table source API."""
	return DdicTableSourceOutput(
		uri=f"/sap/bc/adt/ddic/tables/{name.lower()}/source/main",
		name=name.upper(),
		source=response.text,
		etag=response.headers.get("ETag", "") or "",
		lastModified=response.headers.get("Last-Modified", "") or "",
	)


def parse_ddic_table_create_response(response) -> DdicTableCreateResponse:
	"""Parse XML response from table creation API."""
	try:
		output = _parse_ddic_table_create_response(response)
		return DdicTableCreateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table created successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableCreateResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC table creation response: {str(e)}",
			"data": None
		})


def parse_ddic_table_read_response(systemId: str, name: str, response) -> DdicTableReadResponse:
	"""Parse source response from table read API."""
	try:
		output = _parse_ddic_table_source_response(systemId, name, response)
		return DdicTableReadResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table source read successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableReadResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC table source response: {str(e)}",
			"data": None
		})


def parse_ddic_table_lock_response(response) -> DdicTableLockResponse:
	"""Parse XML response from DDIC table lock API."""
	try:
		data_dict = xmltodict.parse(response.text)
		data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {})
		output = DdicTableLockOutput(
			lockHandle=data_root.get("LOCK_HANDLE", "") or "",
			corrNr=data_root.get("CORRNR", "") or "",
			corrUser=data_root.get("CORRUSER", "") or "",
			corrText=data_root.get("CORRTEXT", "") or "",
			isLocal=_parse_bool(data_root.get("IS_LOCAL")),
			isLinkUp=_parse_bool(data_root.get("IS_LINK_UP")),
			modificationSupport=data_root.get("MODIFICATION_SUPPORT", "") or "",
			scopeMessages=data_root.get("SCOPE_MESSAGES", "") or ""
		)
		return DdicTableLockResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table locked successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableLockResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC table lock response: {str(e)}",
			"data": None
		})


def _get_ddic_table_source(systemId: str, name: str):
	"""Fetch the raw source of a DDIC table."""
	system_config = get_system_config(systemId)
	url = f"{system_config.server}/sap/bc/adt/ddic/tables/{name.lower()}/source/main"
	headers = {
		"Accept": "text/plain",
		"Cache-Control": "no-cache"
	}
	params = {"version": "workingArea"}
	return get_session(systemId).get(url, headers=headers, params=params)


def call_ddic_table_create(
	systemId: str,
	name: str,
	description: str,
	packageName: str = "$TMP",
	transportNumber: str = "",
	responsible: str = "",
	language: str = "",
) -> DdicTableCreateResponse:
	"""Create a DDIC table in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableCreateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot create the DDIC table because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		effective_language = language or system_config.language or "EN"
		effective_responsible = responsible or system_config.user or ""
		url = f"{system_config.server}/sap/bc/adt/ddic/tables"
		headers = {
			"Content-Type": "application/vnd.sap.adt.tables.v2+xml",
			"Accept": "application/vnd.sap.adt.blues.v1+xml, application/vnd.sap.adt.tables.v2+xml"
		}
		params = {}
		if transportNumber:
			params["corrNr"] = transportNumber
		payload = _build_table_create_payload(name, description, packageName, effective_responsible, effective_language)
		response = get_session(systemId).post(url, headers=headers, params=params, data=payload.encode("utf-8"))

		if response.status_code != 201:
			return DdicTableCreateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table creation request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		return parse_ddic_table_create_response(response)
	except Exception as e:
		return DdicTableCreateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while creating the DDIC table: {str(e)}",
			"data": None
		})


def call_ddic_table_read(systemId: str, name: str) -> DdicTableReadResponse:
	"""Read the source of a DDIC table from the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableReadResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot read the DDIC table because no SAP session is available: {error_msg}",
				"data": None
			})

		response = _get_ddic_table_source(systemId, name)
		if response.status_code != 200:
			return DdicTableReadResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table read request: {response.text}",
				"data": None
			})

		return parse_ddic_table_read_response(systemId, name, response)
	except Exception as e:
		return DdicTableReadResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while reading the DDIC table: {str(e)}",
			"data": None
		})


def call_ddic_table_read_raw_content(systemId: str, name: str) -> str:
	"""Read the raw source/main text of a DDIC table."""
	is_logged_in, error_msg = ensure_login(systemId)
	if not is_logged_in:
		raise RuntimeError(f"Cannot read the raw DDIC table source because no SAP session is available: {error_msg}")

	response = _get_ddic_table_source(systemId, name)
	if response.status_code != 200:
		raise RuntimeError(f"ADT rejected the raw DDIC table read request: {response.text}")

	return response.text


def call_ddic_table_update(
	systemId: str,
	name: str,
	lockHandle: str,
	request: DdicTableUpdateRequest,
	transportNumber: str = "",
) -> DdicTableUpdateResponse:
	"""Update the source of a DDIC table in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableUpdateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the DDIC table because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/tables/{name.lower()}/source/main"
		headers = {
			"Content-Type": "text/plain; charset=utf-8",
			"Accept": "text/plain"
		}
		params = {"lockHandle": lockHandle}
		if transportNumber:
			params["corrNr"] = transportNumber

		response = get_session(systemId).put(url, headers=headers, params=params, data=request.source.encode("utf-8"))
		if response.status_code != 200:
			return DdicTableUpdateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table update request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		output = _parse_ddic_table_source_response(systemId, name, response)
		return DdicTableUpdateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table updated successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableUpdateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the DDIC table: {str(e)}",
			"data": None
		})


def call_ddic_table_lock(systemId: str, name: str, accessMode: str = "MODIFY") -> DdicTableLockResponse:
	"""Lock a DDIC table in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableLockResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot lock the DDIC table because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/tables/{name.lower()}"
		headers = build_adt_headers(
			sessionType="stateful",
			extra={
				"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
			}
		)
		params = {"_action": "LOCK", "accessMode": accessMode}
		response = get_session(systemId).post(url, headers=headers, params=params)

		if response.status_code != 200:
			return DdicTableLockResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table lock request: {response.text}",
				"data": None
			})

		return parse_ddic_table_lock_response(response)
	except Exception as e:
		return DdicTableLockResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while locking the DDIC table: {str(e)}",
			"data": None
		})


def call_ddic_table_unlock(systemId: str, name: str, lockHandle: str) -> DdicTableUnlockResponse:
	"""Unlock a DDIC table in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableUnlockResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot unlock the DDIC table because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/tables/{name.lower()}"
		headers = build_adt_headers(sessionType="stateful")
		params = {"_action": "UNLOCK", "lockHandle": lockHandle}
		response = get_session(systemId).post(url, headers=headers, params=params)

		if response.status_code != 200:
			return DdicTableUnlockResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table unlock request: {response.text}",
				"data": None
			})

		return DdicTableUnlockResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table unlocked successfully.",
			"data": None
		})
	except Exception as e:
		return DdicTableUnlockResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while unlocking the DDIC table: {str(e)}",
			"data": None
		})
# endregion
