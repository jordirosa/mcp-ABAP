from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
import configuration
from generics import ApiResponse
from connection.connection import build_adt_headers, ensure_login


# region DDIC Domains
class DdicDomainOutput(BaseModel):
	"""Normalized DDIC domain metadata returned by ADT."""
	uri: str = Field(..., description="ADT URI of the DDIC domain.")
	name: str = Field(..., description="Technical name of the DDIC domain.")
	type: str = Field(..., description="ADT object type of the DDIC domain.")
	description: str = Field(default="", description="Short description of the DDIC domain.")
	language: str = Field(default="", description="Language key stored in the DDIC domain metadata.")
	responsible: str = Field(default="", description="Responsible SAP user for the DDIC domain.")
	packageName: str = Field(default="", description="Package that contains the DDIC domain.")
	version: str = Field(default="", description="Version status reported by ADT, such as active or inactive.")
	createdAt: str = Field(default="", description="UTC timestamp when the DDIC domain was created.")
	createdBy: str = Field(default="", description="SAP user who created the DDIC domain.")
	changedAt: str = Field(default="", description="UTC timestamp of the latest DDIC domain change.")
	changedBy: str = Field(default="", description="SAP user who last changed the DDIC domain.")
	abapLanguageVersion: str = Field(default="", description="ABAP language version assigned to the DDIC domain.")
	dataType: str = Field(default="", description="Underlying DDIC data type.")
	length: int = Field(default=0, description="Technical length of the DDIC domain.")
	decimals: int = Field(default=0, description="Number of decimal places defined for the DDIC domain.")
	outputLength: int = Field(default=0, description="Output length used when the DDIC domain is displayed.")
	outputStyle: str = Field(default="", description="Output style code returned by ADT.")
	conversionExit: str = Field(default="", description="Conversion exit assigned to the DDIC domain.")
	signExists: bool = Field(default=False, description="Whether signed values are allowed.")
	lowercase: bool = Field(default=False, description="Whether lowercase characters are allowed.")
	ampmFormat: bool = Field(default=False, description="Whether AM/PM formatting is enabled.")
	valueTableRef: str = Field(default="", description="Value table reference, when one is assigned.")
	appendExists: bool = Field(default=False, description="Whether append values are defined.")
	fixValues: list[dict] = Field(default_factory=list, description="Fixed values defined for the DDIC domain.")


class DdicDomainCreateResponse(ApiResponse[DdicDomainOutput]):
	"""Response model for DDIC domain creation API call."""


class DdicDomainReadResponse(ApiResponse[DdicDomainOutput]):
	"""Response model for DDIC domain read API call."""


class DdicDomainUpdateResponse(ApiResponse[DdicDomainOutput]):
	"""Response model for DDIC domain update API call."""


class DdicDomainFixValue(BaseModel):
	"""Single fixed value entry used when updating a DDIC domain."""
	low: str = Field(..., description="Low value of the fixed value entry.")
	text: str = Field(..., description="Description text of the fixed value entry.")
	high: str = Field(default="", description="Optional high value for interval-based fixed values.")


class DdicDomainUpdateRequest(BaseModel):
	"""Subset of DDIC domain attributes that can be changed by the update operation."""
	description: str | None = Field(None, description="New short description for the DDIC domain.")
	dataType: str | None = Field(None, description="New DDIC data type, such as CHAR, NUMC, or DEC.")
	length: int | None = Field(None, description="New technical length.")
	decimals: int | None = Field(None, description="New number of decimal places.")
	outputLength: int | None = Field(None, description="New output length.")
	outputStyle: str | None = Field(None, description="New output style code.")
	conversionExit: str | None = Field(None, description="New conversion exit.")
	signExists: bool | None = Field(None, description="Set whether signed values are allowed.")
	lowercase: bool | None = Field(None, description="Set whether lowercase characters are allowed.")
	ampmFormat: bool | None = Field(None, description="Set whether AM/PM formatting is enabled.")
	valueTableRef: str | None = Field(None, description="New value table reference.")
	appendExists: bool | None = Field(None, description="Set whether append values are defined.")
	fixValues: list[DdicDomainFixValue] | None = Field(None, description="Full replacement list of fixed values. Omit this field to keep the existing fixed values.")


class DdicDomainLockOutput(BaseModel):
	"""Lock metadata returned by the internal DDIC domain lock operation."""
	lockHandle: str = Field(..., description="Lock handle returned by ADT.")
	corrNr: str = Field(default="", description="Transport request number proposed by SAP for the lock, when applicable.")
	corrUser: str = Field(default="", description="Owner of the transport request.")
	corrText: str = Field(default="", description="Description of the transport request.")
	isLocal: bool = Field(default=False, description="Whether the locked object is local.")
	isLinkUp: bool = Field(default=False, description="Whether SAP reports a link-up for the lock.")
	modificationSupport: str = Field(default="", description="Modification support information returned by ADT.")
	scopeMessages: str = Field(default="", description="Additional scope messages returned by ADT.")


class DdicDomainLockResponse(ApiResponse[DdicDomainLockOutput]):
	"""Response model for DDIC domain lock API call."""


class DdicDomainUnlockResponse(ApiResponse[BaseModel]):
	"""Response model for DDIC domain unlock API call."""


def _build_domain_create_payload(
	name: str,
	description: str,
	package_name: str,
	responsible: str,
	language: str,
) -> str:
	"""Build XML payload for ADT domain creation."""
	payload = {
		"doma:domain": {
			"@xmlns:adtcore": "http://www.sap.com/adt/core",
			"@xmlns:doma": "http://www.sap.com/dictionary/domain",
			"@adtcore:description": description,
			"@adtcore:language": language,
			"@adtcore:name": name,
			"@adtcore:type": "DOMA/DD",
			"@adtcore:masterLanguage": language,
			"@adtcore:responsible": responsible,
			"adtcore:packageRef": {
				"@adtcore:name": package_name
			}
		}
	}

	return xmltodict.unparse(payload, pretty=False)


def _ensure_list(value):
	"""Normalize XML nodes that can appear either once or many times."""
	if value is None or value == "":
		return []
	if isinstance(value, list):
		return value
	return [value]


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


def _parse_ddic_domain_response(response):
	"""Parse XML response from DDIC domain API and return a DdicDomainOutput object."""
	data_dict = xmltodict.parse(response.text)
	domain_root = data_dict.get("doma:domain", {})
	package_ref = domain_root.get("adtcore:packageRef", {}) or {}
	content = domain_root.get("doma:content", {}) or {}
	type_information = content.get("doma:typeInformation", {}) or {}
	output_information = content.get("doma:outputInformation", {}) or {}
	value_information = content.get("doma:valueInformation", {}) or {}
	fix_values_root = value_information.get("doma:fixValues", {}) or {}
	raw_fix_values = _ensure_list(fix_values_root.get("doma:fixValue"))
	fix_values = []

	for item in raw_fix_values:
		if not isinstance(item, dict):
			continue
		fix_values.append({
			"position": item.get("doma:position", "") or "",
			"low": item.get("doma:low", "") or "",
			"high": item.get("doma:high", "") or "",
			"text": item.get("doma:text", "") or ""
		})

	return DdicDomainOutput(
		uri=response.headers.get("Location", "") or f"/sap/bc/adt/ddic/domains/{domain_root.get('@adtcore:name', '').lower()}",
		name=domain_root.get("@adtcore:name", ""),
		type=domain_root.get("@adtcore:type", ""),
		description=domain_root.get("@adtcore:description", ""),
		language=domain_root.get("@adtcore:language", ""),
		responsible=domain_root.get("@adtcore:responsible", ""),
		packageName=package_ref.get("@adtcore:name", ""),
		version=domain_root.get("@adtcore:version", ""),
		createdAt=domain_root.get("@adtcore:createdAt", ""),
		createdBy=domain_root.get("@adtcore:createdBy", ""),
		changedAt=domain_root.get("@adtcore:changedAt", ""),
		changedBy=domain_root.get("@adtcore:changedBy", ""),
		abapLanguageVersion=domain_root.get("@adtcore:abapLanguageVersion", ""),
		dataType=type_information.get("doma:datatype", "") or "",
		length=_parse_int(type_information.get("doma:length")),
		decimals=_parse_int(type_information.get("doma:decimals")),
		outputLength=_parse_int(output_information.get("doma:length")),
		outputStyle=output_information.get("doma:style", "") or "",
		conversionExit=output_information.get("doma:conversionExit", "") or "",
		signExists=_parse_bool(output_information.get("doma:signExists")),
		lowercase=_parse_bool(output_information.get("doma:lowercase")),
		ampmFormat=_parse_bool(output_information.get("doma:ampmFormat")),
		valueTableRef=value_information.get("doma:valueTableRef", "") or "",
		appendExists=_parse_bool(value_information.get("doma:appendExists")),
		fixValues=fix_values
	)


def _get_ddic_domain_xml(systemId: str, name: str):
	"""Fetch the raw ADT XML for a DDIC domain."""
	system_config = get_system_config(systemId)
	url = f"{system_config.server}/sap/bc/adt/ddic/domains/{name.lower()}"
	headers = {
		"Accept": "application/vnd.sap.adt.domains.v1+xml, application/vnd.sap.adt.domains.v2+xml"
	}

	response = get_session(systemId).get(url, headers=headers)
	return response


def _set_if_provided(container: dict, key: str, value):
	"""Update XML payload values only when the caller provided a value."""
	if value is not None:
		container[key] = value


def _build_fix_values_payload(fixValues: list[DdicDomainFixValue]) -> dict:
	"""Build XML payload fragment for domain fixed values."""
	if not fixValues:
		return {"doma:fixValue": []}

	return {
		"doma:fixValue": [
			{
				"doma:low": item.low,
				"doma:high": item.high,
				"doma:text": item.text
			}
			for item in fixValues
		]
	}


def _build_domain_update_payload(
	current_xml: str,
	description: str | None = None,
	dataType: str | None = None,
	length: int | None = None,
	decimals: int | None = None,
	outputLength: int | None = None,
	outputStyle: str | None = None,
	conversionExit: str | None = None,
	signExists: bool | None = None,
	lowercase: bool | None = None,
	ampmFormat: bool | None = None,
	valueTableRef: str | None = None,
	appendExists: bool | None = None,
	fixValues: list[DdicDomainFixValue] | None = None,
) -> str:
	"""Build XML payload for ADT domain modification preserving current metadata."""
	payload = xmltodict.parse(current_xml)
	domain_root = payload.get("doma:domain", {})
	content = domain_root.setdefault("doma:content", {})
	type_information = content.setdefault("doma:typeInformation", {})
	output_information = content.setdefault("doma:outputInformation", {})
	value_information = content.setdefault("doma:valueInformation", {})

	_set_if_provided(domain_root, "@adtcore:description", description)
	_set_if_provided(type_information, "doma:datatype", dataType)
	_set_if_provided(type_information, "doma:length", str(length) if length is not None else None)
	_set_if_provided(type_information, "doma:decimals", str(decimals) if decimals is not None else None)
	_set_if_provided(output_information, "doma:length", str(outputLength) if outputLength is not None else None)
	_set_if_provided(output_information, "doma:style", outputStyle)
	_set_if_provided(output_information, "doma:conversionExit", conversionExit)
	_set_if_provided(output_information, "doma:signExists", str(signExists).lower() if signExists is not None else None)
	_set_if_provided(output_information, "doma:lowercase", str(lowercase).lower() if lowercase is not None else None)
	_set_if_provided(output_information, "doma:ampmFormat", str(ampmFormat).lower() if ampmFormat is not None else None)

	if valueTableRef is not None:
		current_value_table = value_information.get("doma:valueTableRef", {})
		if isinstance(current_value_table, dict):
			current_value_table["@adtcore:name"] = valueTableRef
			value_information["doma:valueTableRef"] = current_value_table
		else:
			value_information["doma:valueTableRef"] = {"@adtcore:name": valueTableRef}

	_set_if_provided(value_information, "doma:appendExists", str(appendExists).lower() if appendExists is not None else None)

	if fixValues is not None:
		value_information["doma:fixValues"] = _build_fix_values_payload(fixValues)

	return xmltodict.unparse(payload, pretty=False)


def parse_ddic_domain_create_response(response) -> DdicDomainCreateResponse:
	"""Parse XML response from domain creation API and return DdicDomainCreateResponse object."""
	try:
		output = _parse_ddic_domain_response(response)

		return DdicDomainCreateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC domain created successfully.",
			"data": output
		})

	except Exception as e:
		return DdicDomainCreateResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC domain creation response: {str(e)}",
			"data": None
		})


def parse_ddic_domain_read_response(response) -> DdicDomainReadResponse:
	"""Parse XML response from domain read API and return DdicDomainReadResponse object."""
	try:
		output = _parse_ddic_domain_response(response)

		return DdicDomainReadResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC domain read successfully.",
			"data": output
		})

	except Exception as e:
		return DdicDomainReadResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC domain response: {str(e)}",
			"data": None
		})


def parse_ddic_domain_lock_response(response) -> DdicDomainLockResponse:
	"""Parse XML response from DDIC domain lock API."""
	try:
		data_dict = xmltodict.parse(response.text)
		data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {})

		output = DdicDomainLockOutput(
			lockHandle=data_root.get("LOCK_HANDLE", "") or "",
			corrNr=data_root.get("CORRNR", "") or "",
			corrUser=data_root.get("CORRUSER", "") or "",
			corrText=data_root.get("CORRTEXT", "") or "",
			isLocal=_parse_bool(data_root.get("IS_LOCAL")),
			isLinkUp=_parse_bool(data_root.get("IS_LINK_UP")),
			modificationSupport=data_root.get("MODIFICATION_SUPPORT", "") or "",
			scopeMessages=data_root.get("SCOPE_MESSAGES", "") or ""
		)

		return DdicDomainLockResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC domain locked successfully.",
			"data": output
		})

	except Exception as e:
		return DdicDomainLockResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC domain lock response: {str(e)}",
			"data": None
		})


def call_ddic_domain_create(
	systemId: str,
	name: str,
	description: str,
	packageName: str = "$TMP",
	transportNumber: str = "",
	responsible: str = "",
	language: str = "",
) -> DdicDomainCreateResponse:
	"""Create a DDIC domain in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDomainCreateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot create the DDIC domain because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		effective_language = language or system_config.language or "EN"
		effective_responsible = responsible or system_config.user or ""
		url = f"{system_config.server}/sap/bc/adt/ddic/domains"
		headers = {
			"Content-Type": "application/vnd.sap.adt.domains.v2+xml",
			"Accept": "application/vnd.sap.adt.domains.v1+xml, application/vnd.sap.adt.domains.v2+xml"
		}
		params = {}
		if transportNumber:
			params["corrNr"] = transportNumber
		payload = _build_domain_create_payload(
			name=name,
			description=description,
			package_name=packageName,
			responsible=effective_responsible,
			language=effective_language
		)

		response = get_session(systemId).post(url, headers=headers, params=params, data=payload.encode("utf-8"))

		if response.status_code != 201:
			return DdicDomainCreateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC domain creation request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		return parse_ddic_domain_create_response(response)

	except Exception as e:
		return DdicDomainCreateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while creating the DDIC domain: {str(e)}",
			"data": None
		})


def call_ddic_domain_read(systemId: str, name: str) -> DdicDomainReadResponse:
	"""Read a DDIC domain from the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDomainReadResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot read the DDIC domain because no SAP session is available: {error_msg}",
				"data": None
			})

		response = _get_ddic_domain_xml(systemId, name)

		if response.status_code != 200:
			return DdicDomainReadResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC domain read request: {response.text}",
				"data": None
			})

		return parse_ddic_domain_read_response(response)

	except Exception as e:
		return DdicDomainReadResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while reading the DDIC domain: {str(e)}",
			"data": None
		})


def call_ddic_domain_read_raw_content(systemId: str, name: str) -> str:
	"""Read the raw ADT XML of a DDIC domain."""
	is_logged_in, error_msg = ensure_login(systemId)
	if not is_logged_in:
		raise RuntimeError(f"Cannot read the raw DDIC domain because no SAP session is available: {error_msg}")

	response = _get_ddic_domain_xml(systemId, name)
	if response.status_code != 200:
		raise RuntimeError(f"ADT rejected the raw DDIC domain read request: {response.text}")

	return response.text


def call_ddic_domain_update(
	systemId: str,
	name: str,
	lockHandle: str,
	request: DdicDomainUpdateRequest,
	transportNumber: str = "",
) -> DdicDomainUpdateResponse:
	"""Update a DDIC domain in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDomainUpdateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the DDIC domain because no SAP session is available: {error_msg}",
				"data": None
			})

		current_response = _get_ddic_domain_xml(systemId, name)
		if current_response.status_code != 200:
			return DdicDomainUpdateResponse.model_validate({
				"result": False,
				"httpCode": current_response.status_code,
				"httpReason": current_response.reason,
				"message": f"Failed to read the current DDIC domain state before updating it: {current_response.text}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/domains/{name.lower()}"
		headers = {
			"Content-Type": "application/vnd.sap.adt.domains.v2+xml; charset=utf-8",
			"Accept": "application/vnd.sap.adt.domains.v1+xml, application/vnd.sap.adt.domains.v2+xml"
		}
		params = {
			"lockHandle": lockHandle
		}
		if transportNumber:
			params["corrNr"] = transportNumber
		payload = _build_domain_update_payload(
			current_xml=current_response.text,
			description=request.description,
			dataType=request.dataType,
			length=request.length,
			decimals=request.decimals,
			outputLength=request.outputLength,
			outputStyle=request.outputStyle,
			conversionExit=request.conversionExit,
			signExists=request.signExists,
			lowercase=request.lowercase,
			ampmFormat=request.ampmFormat,
			valueTableRef=request.valueTableRef,
			appendExists=request.appendExists,
			fixValues=request.fixValues
		)

		response = get_session(systemId).put(url, headers=headers, params=params, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return DdicDomainUpdateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC domain update request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		output = _parse_ddic_domain_response(response)
		return DdicDomainUpdateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC domain updated successfully.",
			"data": output
		})

	except Exception as e:
		return DdicDomainUpdateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the DDIC domain: {str(e)}",
			"data": None
		})


def call_ddic_domain_update_raw(
	systemId: str,
	name: str,
	lockHandle: str,
	rawXml: str,
	transportNumber: str = "",
) -> DdicDomainUpdateResponse:
	"""Update a DDIC domain using raw ADT XML."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDomainUpdateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the DDIC domain because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/domains/{name.lower()}"
		headers = {
			"Content-Type": "application/vnd.sap.adt.domains.v2+xml; charset=utf-8",
			"Accept": "application/vnd.sap.adt.domains.v1+xml, application/vnd.sap.adt.domains.v2+xml"
		}
		params = {"lockHandle": lockHandle}
		if transportNumber:
			params["corrNr"] = transportNumber

		response = get_session(systemId).put(url, headers=headers, params=params, data=rawXml.encode("utf-8"))
		if response.status_code != 200:
			return DdicDomainUpdateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC domain raw update request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		output = _parse_ddic_domain_response(response)
		return DdicDomainUpdateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC domain updated successfully from raw XML.",
			"data": output
		})
	except Exception as e:
		return DdicDomainUpdateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the DDIC domain from raw XML: {str(e)}",
			"data": None
		})


def call_ddic_domain_lock(systemId: str, name: str, accessMode: str = "MODIFY") -> DdicDomainLockResponse:
	"""Lock a DDIC domain in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDomainLockResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot lock the DDIC domain because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/domains/{name.lower()}"
		headers = build_adt_headers(
			sessionType="stateful",
			extra={
				"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
			}
		)
		params = {
			"_action": "LOCK",
			"accessMode": accessMode
		}

		response = get_session(systemId).post(url, headers=headers, params=params)

		if response.status_code != 200:
			return DdicDomainLockResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC domain lock request: {response.text}",
				"data": None
			})

		return parse_ddic_domain_lock_response(response)

	except Exception as e:
		return DdicDomainLockResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while locking the DDIC domain: {str(e)}",
			"data": None
		})


def call_ddic_domain_unlock(systemId: str, name: str, lockHandle: str) -> DdicDomainUnlockResponse:
	"""Unlock a DDIC domain in the SAP system through ADT."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicDomainUnlockResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot unlock the DDIC domain because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/domains/{name.lower()}"
		headers = build_adt_headers(sessionType="stateful")
		params = {
			"_action": "UNLOCK",
			"lockHandle": lockHandle
		}

		response = get_session(systemId).post(url, headers=headers, params=params)

		if response.status_code != 200:
			return DdicDomainUnlockResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC domain unlock request: {response.text}",
				"data": None
			})

		return DdicDomainUnlockResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC domain unlocked successfully.",
			"data": None
		})

	except Exception as e:
		return DdicDomainUnlockResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while unlocking the DDIC domain: {str(e)}",
			"data": None
		})
# endregion
