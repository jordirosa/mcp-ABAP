from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from generics import ApiResponse
from connection.connection import build_adt_headers, ensure_login


# region DDIC Data Elements
class DdicDataElementOutput(BaseModel):
	"""Normalized DDIC data element metadata returned by ADT."""
	uri: str = Field(..., description="ADT URI of the DDIC data element.")
	name: str = Field(..., description="Technical name of the DDIC data element.")
	type: str = Field(..., description="ADT object type of the DDIC data element.")
	description: str = Field(default="", description="Short description of the DDIC data element.")
	language: str = Field(default="", description="Language key stored in the DDIC data element metadata.")
	responsible: str = Field(default="", description="Responsible SAP user for the DDIC data element.")
	packageName: str = Field(default="", description="Package that contains the DDIC data element.")
	version: str = Field(default="", description="Version status reported by ADT, such as active or inactive.")
	createdAt: str = Field(default="", description="UTC timestamp when the DDIC data element was created.")
	createdBy: str = Field(default="", description="SAP user who created the DDIC data element.")
	changedAt: str = Field(default="", description="UTC timestamp of the latest DDIC data element change.")
	changedBy: str = Field(default="", description="SAP user who last changed the DDIC data element.")
	abapLanguageVersion: str = Field(default="", description="ABAP language version assigned to the DDIC data element.")
	typeKind: str = Field(default="", description="Type category of the DDIC data element, such as domain.")
	typeName: str = Field(default="", description="Referenced type name used by the DDIC data element.")
	dataType: str = Field(default="", description="Resolved SAP data type of the DDIC data element.")
	dataTypeLength: int = Field(default=0, description="Resolved technical data type length.")
	dataTypeDecimals: int = Field(default=0, description="Resolved technical number of decimals.")
	shortFieldLabel: str = Field(default="", description="Short field label.")
	shortFieldLength: int = Field(default=0, description="Configured short field label length.")
	shortFieldMaxLength: int = Field(default=0, description="Maximum allowed short field label length.")
	mediumFieldLabel: str = Field(default="", description="Medium field label.")
	mediumFieldLength: int = Field(default=0, description="Configured medium field label length.")
	mediumFieldMaxLength: int = Field(default=0, description="Maximum allowed medium field label length.")
	longFieldLabel: str = Field(default="", description="Long field label.")
	longFieldLength: int = Field(default=0, description="Configured long field label length.")
	longFieldMaxLength: int = Field(default=0, description="Maximum allowed long field label length.")
	headingFieldLabel: str = Field(default="", description="Column heading field label.")
	headingFieldLength: int = Field(default=0, description="Configured column heading length.")
	headingFieldMaxLength: int = Field(default=0, description="Maximum allowed column heading length.")
	searchHelp: str = Field(default="", description="Assigned search help.")
	searchHelpParameter: str = Field(default="", description="Parameter name used for the assigned search help.")
	setGetParameter: str = Field(default="", description="SET/GET parameter ID.")
	defaultComponentName: str = Field(default="", description="Default component name.")
	deactivateInputHistory: bool = Field(default=False, description="Whether input history is deactivated.")
	changeDocument: bool = Field(default=False, description="Whether change document logging is enabled.")
	leftToRightDirection: bool = Field(default=False, description="Whether left-to-right direction is enforced.")
	deactivateBIDIFiltering: bool = Field(default=False, description="Whether BIDI filtering is deactivated.")


class DdicDataElementCreateResponse(ApiResponse[DdicDataElementOutput]):
	"""Response model for DDIC data element creation API call."""


class DdicDataElementReadResponse(ApiResponse[DdicDataElementOutput]):
	"""Response model for DDIC data element read API call."""


class DdicDataElementUpdateResponse(ApiResponse[DdicDataElementOutput]):
	"""Response model for DDIC data element update API call."""


class DdicDataElementUpdateRequest(BaseModel):
	"""Subset of DDIC data element attributes that can be changed by the update operation."""
	description: str | None = Field(None, description="New short description for the DDIC data element.")
	typeKind: str | None = Field(None, description="New type category, such as domain.")
	typeName: str | None = Field(None, description="New referenced type name, such as a domain name.")
	shortFieldLabel: str | None = Field(None, description="New short field label.")
	shortFieldLength: int | None = Field(None, description="New short field label length.")
	mediumFieldLabel: str | None = Field(None, description="New medium field label.")
	mediumFieldLength: int | None = Field(None, description="New medium field label length.")
	longFieldLabel: str | None = Field(None, description="New long field label.")
	longFieldLength: int | None = Field(None, description="New long field label length.")
	headingFieldLabel: str | None = Field(None, description="New column heading field label.")
	headingFieldLength: int | None = Field(None, description="New column heading length.")
	searchHelp: str | None = Field(None, description="New search help name.")
	searchHelpParameter: str | None = Field(None, description="New search help parameter name.")
	setGetParameter: str | None = Field(None, description="New SET/GET parameter ID.")
	defaultComponentName: str | None = Field(None, description="New default component name.")
	deactivateInputHistory: bool | None = Field(None, description="Set whether input history is deactivated.")
	changeDocument: bool | None = Field(None, description="Set whether change document logging is enabled.")
	leftToRightDirection: bool | None = Field(None, description="Set whether left-to-right direction is enforced.")
	deactivateBIDIFiltering: bool | None = Field(None, description="Set whether BIDI filtering is deactivated.")


class DdicDataElementLockOutput(BaseModel):
	"""Lock metadata returned by the internal DDIC data element lock operation."""
	lockHandle: str = Field(..., description="Lock handle returned by ADT.")
	corrNr: str = Field(default="", description="Transport request number proposed by SAP for the lock, when applicable.")
	corrUser: str = Field(default="", description="Owner of the transport request.")
	corrText: str = Field(default="", description="Description of the transport request.")
	isLocal: bool = Field(default=False, description="Whether the locked object is local.")
	isLinkUp: bool = Field(default=False, description="Whether SAP reports a link-up for the lock.")
	modificationSupport: str = Field(default="", description="Modification support information returned by ADT.")
	scopeMessages: str = Field(default="", description="Additional scope messages returned by ADT.")


class DdicDataElementLockResponse(ApiResponse[DdicDataElementLockOutput]):
	"""Response model for DDIC data element lock API call."""


class DdicDataElementUnlockResponse(ApiResponse[BaseModel]):
	"""Response model for DDIC data element unlock API call."""


def _parse_int(value: str) -> int:
	"""Parse integer values returned by ADT XML payloads."""
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _parse_bool(value) -> bool:
	"""Parse boolean values returned by ADT XML payloads."""
	if isinstance(value, bool):
		return value
	return str(value).lower() in ("true", "x")


def _set_if_provided(container: dict, key: str, value):
	"""Update XML payload values only when the caller provided a value."""
	if value is not None:
		container[key] = value


def _build_dataelement_create_payload(
	name: str,
	description: str,
	package_name: str,
	responsible: str,
	language: str,
) -> str:
	"""Build XML payload for ADT data element creation."""
	payload = {
		"blue:wbobj": {
			"@xmlns:adtcore": "http://www.sap.com/adt/core",
			"@xmlns:blue": "http://www.sap.com/wbobj/dictionary/dtel",
			"@adtcore:description": description,
			"@adtcore:language": language,
			"@adtcore:name": name,
			"@adtcore:type": "DTEL/DE",
			"@adtcore:masterLanguage": language,
			"@adtcore:responsible": responsible,
			"adtcore:packageRef": {
				"@adtcore:name": package_name
			}
		}
	}

	return xmltodict.unparse(payload, pretty=False)


def _parse_ddic_dataelement_response(response) -> DdicDataElementOutput:
	"""Parse XML response from DDIC data element API and return a DdicDataElementOutput object."""
	data_dict = xmltodict.parse(response.text)
	root = data_dict.get("blue:wbobj", {})
	package_ref = root.get("adtcore:packageRef", {}) or {}
	data_element = root.get("dtel:dataElement", {}) or {}

	return DdicDataElementOutput(
		uri=response.headers.get("Location", "") or f"/sap/bc/adt/ddic/dataelements/{root.get('@adtcore:name', '').lower()}",
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
		typeKind=data_element.get("dtel:typeKind", "") or "",
		typeName=data_element.get("dtel:typeName", "") or "",
		dataType=data_element.get("dtel:dataType", "") or "",
		dataTypeLength=_parse_int(data_element.get("dtel:dataTypeLength")),
		dataTypeDecimals=_parse_int(data_element.get("dtel:dataTypeDecimals")),
		shortFieldLabel=data_element.get("dtel:shortFieldLabel", "") or "",
		shortFieldLength=_parse_int(data_element.get("dtel:shortFieldLength")),
		shortFieldMaxLength=_parse_int(data_element.get("dtel:shortFieldMaxLength")),
		mediumFieldLabel=data_element.get("dtel:mediumFieldLabel", "") or "",
		mediumFieldLength=_parse_int(data_element.get("dtel:mediumFieldLength")),
		mediumFieldMaxLength=_parse_int(data_element.get("dtel:mediumFieldMaxLength")),
		longFieldLabel=data_element.get("dtel:longFieldLabel", "") or "",
		longFieldLength=_parse_int(data_element.get("dtel:longFieldLength")),
		longFieldMaxLength=_parse_int(data_element.get("dtel:longFieldMaxLength")),
		headingFieldLabel=data_element.get("dtel:headingFieldLabel", "") or "",
		headingFieldLength=_parse_int(data_element.get("dtel:headingFieldLength")),
		headingFieldMaxLength=_parse_int(data_element.get("dtel:headingFieldMaxLength")),
		searchHelp=data_element.get("dtel:searchHelp", "") or "",
		searchHelpParameter=data_element.get("dtel:searchHelpParameter", "") or "",
		setGetParameter=data_element.get("dtel:setGetParameter", "") or "",
		defaultComponentName=data_element.get("dtel:defaultComponentName", "") or "",
		deactivateInputHistory=_parse_bool(data_element.get("dtel:deactivateInputHistory")),
		changeDocument=_parse_bool(data_element.get("dtel:changeDocument")),
		leftToRightDirection=_parse_bool(data_element.get("dtel:leftToRightDirection")),
		deactivateBIDIFiltering=_parse_bool(data_element.get("dtel:deactivateBIDIFiltering")),
	)


def _get_ddic_dataelement_xml(systemId: str, name: str):
	"""Fetch the raw ADT XML for a DDIC data element."""
	system_config = get_system_config(systemId)
	url = f"{system_config.server}/sap/bc/adt/ddic/dataelements/{name.lower()}"
	headers = {
		"Accept": "application/vnd.sap.adt.dataelements.v1+xml, application/vnd.sap.adt.dataelements.v2+xml"
	}

	return get_session(systemId).get(url, headers=headers)


def _build_dataelement_update_payload(current_xml: str, request: DdicDataElementUpdateRequest) -> str:
	"""Build XML payload for ADT data element update preserving current metadata."""
	payload = xmltodict.parse(current_xml)
	root = payload.get("blue:wbobj", {})
	data_element = root.setdefault("dtel:dataElement", {})

	_set_if_provided(root, "@adtcore:description", request.description)
	_set_if_provided(data_element, "dtel:typeKind", request.typeKind)
	_set_if_provided(data_element, "dtel:typeName", request.typeName)
	_set_if_provided(data_element, "dtel:shortFieldLabel", request.shortFieldLabel)
	_set_if_provided(data_element, "dtel:shortFieldLength", str(request.shortFieldLength) if request.shortFieldLength is not None else None)
	_set_if_provided(data_element, "dtel:mediumFieldLabel", request.mediumFieldLabel)
	_set_if_provided(data_element, "dtel:mediumFieldLength", str(request.mediumFieldLength) if request.mediumFieldLength is not None else None)
	_set_if_provided(data_element, "dtel:longFieldLabel", request.longFieldLabel)
	_set_if_provided(data_element, "dtel:longFieldLength", str(request.longFieldLength) if request.longFieldLength is not None else None)
	_set_if_provided(data_element, "dtel:headingFieldLabel", request.headingFieldLabel)
	_set_if_provided(data_element, "dtel:headingFieldLength", str(request.headingFieldLength) if request.headingFieldLength is not None else None)
	_set_if_provided(data_element, "dtel:searchHelp", request.searchHelp)
	_set_if_provided(data_element, "dtel:searchHelpParameter", request.searchHelpParameter)
	_set_if_provided(data_element, "dtel:setGetParameter", request.setGetParameter)
	_set_if_provided(data_element, "dtel:defaultComponentName", request.defaultComponentName)
	_set_if_provided(data_element, "dtel:deactivateInputHistory", str(request.deactivateInputHistory).lower() if request.deactivateInputHistory is not None else None)
	_set_if_provided(data_element, "dtel:changeDocument", str(request.changeDocument).lower() if request.changeDocument is not None else None)
	_set_if_provided(data_element, "dtel:leftToRightDirection", str(request.leftToRightDirection).lower() if request.leftToRightDirection is not None else None)
	_set_if_provided(data_element, "dtel:deactivateBIDIFiltering", str(request.deactivateBIDIFiltering).lower() if request.deactivateBIDIFiltering is not None else None)

	return xmltodict.unparse(payload, pretty=False)


def parse_ddic_dataelement_create_response(response) -> DdicDataElementCreateResponse:
	"""Parse XML response from data element creation API."""
	try:
		output = _parse_ddic_dataelement_response(response)
		return DdicDataElementCreateResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC data element created successfully.",
			"data": output
		})
	except Exception as e:
		return DdicDataElementCreateResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC data element creation response: {str(e)}",
			"data": None
		})


def parse_ddic_dataelement_read_response(response) -> DdicDataElementReadResponse:
	"""Parse XML response from data element read API."""
	try:
		output = _parse_ddic_dataelement_response(response)
		return DdicDataElementReadResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC data element read successfully.",
			"data": output
		})
	except Exception as e:
		return DdicDataElementReadResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC data element response: {str(e)}",
			"data": None
		})


def parse_ddic_dataelement_lock_response(response) -> DdicDataElementLockResponse:
	"""Parse XML response from DDIC data element lock API."""
	try:
		data_dict = xmltodict.parse(response.text)
		data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {})

		output = DdicDataElementLockOutput(
			lockHandle=data_root.get("LOCK_HANDLE", "") or "",
			corrNr=data_root.get("CORRNR", "") or "",
			corrUser=data_root.get("CORRUSER", "") or "",
			corrText=data_root.get("CORRTEXT", "") or "",
			isLocal=_parse_bool(data_root.get("IS_LOCAL")),
			isLinkUp=_parse_bool(data_root.get("IS_LINK_UP")),
			modificationSupport=data_root.get("MODIFICATION_SUPPORT", "") or "",
			scopeMessages=data_root.get("SCOPE_MESSAGES", "") or ""
		)

		return DdicDataElementLockResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC data element locked successfully.",
			"data": output
		})
	except Exception as e:
		return DdicDataElementLockResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC data element lock response: {str(e)}",
			"data": None
		})


def call_ddic_dataelement_create(
	systemId: str,
	name: str,
	description: str,
	packageName: str = "$TMP",
	transportNumber: str = "",
	responsible: str = "",
	language: str = "",
) -> DdicDataElementCreateResponse:
	"""Create a DDIC data element in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDataElementCreateResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot create the DDIC data element because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		effective_language = language or system_config.language or "EN"
		effective_responsible = responsible or system_config.user or ""
		url = f"{system_config.server}/sap/bc/adt/ddic/dataelements"
		headers = {
			"Content-Type": "application/vnd.sap.adt.dataelements.v2+xml",
			"Accept": "application/vnd.sap.adt.dataelements.v1+xml, application/vnd.sap.adt.dataelements.v2+xml"
		}
		params = {}
		if transportNumber:
			params["corrNr"] = transportNumber
		payload = _build_dataelement_create_payload(
			name=name,
			description=description,
			package_name=packageName,
			responsible=effective_responsible,
			language=effective_language
		)

		response = get_session(systemId).post(url, headers=headers, params=params, data=payload.encode("utf-8"))
		if response.status_code != 201:
			return DdicDataElementCreateResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC data element creation request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		return parse_ddic_dataelement_create_response(response)
	except Exception as e:
		return DdicDataElementCreateResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while creating the DDIC data element: {str(e)}",
			"data": None
		})


def call_ddic_dataelement_read(systemId: str, name: str) -> DdicDataElementReadResponse:
	"""Read a DDIC data element from the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDataElementReadResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot read the DDIC data element because no SAP session is available: {error_msg}",
				"data": None
			})

		response = _get_ddic_dataelement_xml(systemId, name)
		if response.status_code != 200:
			return DdicDataElementReadResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC data element read request: {response.text}",
				"data": None
			})

		return parse_ddic_dataelement_read_response(response)
	except Exception as e:
		return DdicDataElementReadResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while reading the DDIC data element: {str(e)}",
			"data": None
		})


def call_ddic_dataelement_update(
	systemId: str,
	name: str,
	lockHandle: str,
	request: DdicDataElementUpdateRequest,
	transportNumber: str = "",
) -> DdicDataElementUpdateResponse:
	"""Update a DDIC data element in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDataElementUpdateResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the DDIC data element because no SAP session is available: {error_msg}",
				"data": None
			})

		current_response = _get_ddic_dataelement_xml(systemId, name)
		if current_response.status_code != 200:
			return DdicDataElementUpdateResponse.parse_obj({
				"result": False,
				"httpCode": current_response.status_code,
				"httpReason": current_response.reason,
				"message": f"Failed to read the current DDIC data element state before updating it: {current_response.text}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/dataelements/{name.lower()}"
		headers = {
			"Content-Type": "application/vnd.sap.adt.dataelements.v2+xml; charset=utf-8",
			"Accept": "application/vnd.sap.adt.dataelements.v1+xml, application/vnd.sap.adt.dataelements.v2+xml"
		}
		params = {"lockHandle": lockHandle}
		if transportNumber:
			params["corrNr"] = transportNumber
		payload = _build_dataelement_update_payload(current_response.text, request)

		response = get_session(systemId).put(url, headers=headers, params=params, data=payload.encode("utf-8"))
		if response.status_code != 200:
			return DdicDataElementUpdateResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC data element update request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		output = _parse_ddic_dataelement_response(response)
		return DdicDataElementUpdateResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC data element updated successfully.",
			"data": output
		})
	except Exception as e:
		return DdicDataElementUpdateResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the DDIC data element: {str(e)}",
			"data": None
		})


def call_ddic_dataelement_lock(systemId: str, name: str, accessMode: str = "MODIFY") -> DdicDataElementLockResponse:
	"""Lock a DDIC data element in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDataElementLockResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot lock the DDIC data element because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/dataelements/{name.lower()}"
		headers = build_adt_headers(
			sessionType="stateful",
			extra={
				"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
			}
		)
		params = {"_action": "LOCK", "accessMode": accessMode}

		response = get_session(systemId).post(url, headers=headers, params=params)
		if response.status_code != 200:
			return DdicDataElementLockResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC data element lock request: {response.text}",
				"data": None
			})

		return parse_ddic_dataelement_lock_response(response)
	except Exception as e:
		return DdicDataElementLockResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while locking the DDIC data element: {str(e)}",
			"data": None
		})


def call_ddic_dataelement_unlock(systemId: str, name: str, lockHandle: str) -> DdicDataElementUnlockResponse:
	"""Unlock a DDIC data element in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDataElementUnlockResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot unlock the DDIC data element because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/dataelements/{name.lower()}"
		headers = build_adt_headers(sessionType="stateful")
		params = {"_action": "UNLOCK", "lockHandle": lockHandle}

		response = get_session(systemId).post(url, headers=headers, params=params)
		if response.status_code != 200:
			return DdicDataElementUnlockResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC data element unlock request: {response.text}",
				"data": None
			})

		return DdicDataElementUnlockResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC data element unlocked successfully.",
			"data": None
		})
	except Exception as e:
		return DdicDataElementUnlockResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while unlocking the DDIC data element: {str(e)}",
			"data": None
		})
# endregion
