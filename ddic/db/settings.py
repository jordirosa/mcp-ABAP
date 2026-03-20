from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from generics import ApiResponse
from connection.connection import build_adt_headers, ensure_login


# region DDIC DB Settings
class DdicTableDbSettingsOutput(BaseModel):
	"""Normalized DDIC table database settings returned by ADT."""
	uri: str = Field(..., description="ADT URI of the table database settings resource.")
	name: str = Field(..., description="Technical name of the table whose database settings are returned.")
	type: str = Field(default="", description="ADT object type of the database settings resource.")
	tableUri: str = Field(default="", description="ADT URI of the parent DDIC table.")
	tableType: str = Field(default="", description="ADT object type of the parent DDIC table.")
	tableName: str = Field(default="", description="Technical name of the parent DDIC table.")
	description: str = Field(default="", description="Short description returned by ADT for the settings object.")
	language: str = Field(default="", description="Language key stored in the settings metadata.")
	version: str = Field(default="", description="Version status reported by ADT, such as active or inactive.")
	createdAt: str = Field(default="", description="UTC timestamp when the settings object was created.")
	createdBy: str = Field(default="", description="SAP user who created the settings object.")
	changedAt: str = Field(default="", description="UTC timestamp of the latest settings change.")
	changedBy: str = Field(default="", description="SAP user who last changed the settings object.")
	dataClassCategory: str = Field(default="", description="Data class category.")
	sizeCategory: str = Field(default="", description="Size category.")
	bufferingAllowed: str = Field(default="", description="Whether buffering is allowed and with which SAP code.")
	bufferingType: str = Field(default="", description="Buffering type code.")
	bufferingAreaKeyFields: int = Field(default=0, description="Number of area key fields for generic buffering.")
	storageType: str = Field(default="", description="Storage type code.")
	sharingType: str = Field(default="", description="Sharing type code.")
	loadUnit: str = Field(default="", description="Load unit value.")
	translationValue: str = Field(default="", description="Translation setting value.")
	translationGranularity: str = Field(default="", description="Translation granularity value.")
	translationIsVisible: bool = Field(default=False, description="Whether the translation setting is visible.")
	translationIsEditable: bool = Field(default=False, description="Whether the translation setting is editable.")
	loggingEnabled: bool = Field(default=False, description="Whether table logging is enabled.")
	supportsLoggingAssessment: bool = Field(default=False, description="Whether logging assessment is supported.")
	etag: str = Field(default="", description="ETag returned by ADT for the settings resource.")
	lastModified: str = Field(default="", description="Last-Modified header returned by ADT for the settings resource.")


class DdicTableDbSettingsUpdateRequest(BaseModel):
	"""Subset of database settings attributes that can be changed by the update operation."""
	dataClassCategory: str | None = Field(None, description="New data class category.")
	sizeCategory: str | None = Field(None, description="New size category.")
	bufferingAllowed: str | None = Field(None, description="New buffering allowed code.")
	bufferingType: str | None = Field(None, description="New buffering type code.")
	bufferingAreaKeyFields: int | None = Field(None, description="New number of area key fields for generic buffering.")
	storageType: str | None = Field(None, description="New storage type code.")
	sharingType: str | None = Field(None, description="New sharing type code.")
	loadUnit: str | None = Field(None, description="New load unit value.")
	loggingEnabled: bool | None = Field(None, description="Set whether table logging is enabled.")


class DdicTableDbSettingsReadResponse(ApiResponse[DdicTableDbSettingsOutput]):
	"""Response model for DDIC table database settings read API call."""


class DdicTableDbSettingsUpdateResponse(ApiResponse[DdicTableDbSettingsOutput]):
	"""Response model for DDIC table database settings update API call."""


class DdicTableDbSettingsLockOutput(BaseModel):
	"""Lock metadata returned by the internal DDIC table database settings lock operation."""
	lockHandle: str = Field(..., description="Lock handle returned by ADT.")
	corrNr: str = Field(default="", description="Transport request number proposed by SAP for the lock, when applicable.")
	corrUser: str = Field(default="", description="Owner of the transport request.")
	corrText: str = Field(default="", description="Description of the transport request.")
	isLocal: bool = Field(default=False, description="Whether the locked object is local.")
	isLinkUp: bool = Field(default=False, description="Whether SAP reports a link-up for the lock.")
	modificationSupport: str = Field(default="", description="Modification support information returned by ADT.")
	scopeMessages: str = Field(default="", description="Additional scope messages returned by ADT.")


class DdicTableDbSettingsLockResponse(ApiResponse[DdicTableDbSettingsLockOutput]):
	"""Response model for DDIC table database settings lock API call."""


class DdicTableDbSettingsUnlockResponse(ApiResponse[BaseModel]):
	"""Response model for DDIC table database settings unlock API call."""


def _parse_int(value: str) -> int:
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _parse_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	return str(value).lower() in ("true", "x")


def _set_if_provided(container: dict, key: str, value):
	if value is not None:
		container[key] = value


def _parse_db_settings_response(systemId: str, tableName: str, response) -> DdicTableDbSettingsOutput:
	data_dict = xmltodict.parse(response.text)
	root = data_dict.get("ts:tableSettings", {})
	container_ref = root.get("adtcore:containerRef", {}) or {}
	buffering = root.get("ts:buffering", {}) or {}
	translation = root.get("ts:translation", {}) or {}

	return DdicTableDbSettingsOutput(
		uri=f"/sap/bc/adt/ddic/db/settings/{tableName.lower()}",
		name=root.get("@adtcore:name", "") or tableName.upper(),
		type=root.get("@adtcore:type", "") or "",
		tableUri=container_ref.get("@adtcore:uri", "") or "",
		tableType=container_ref.get("@adtcore:type", "") or "",
		tableName=container_ref.get("@adtcore:name", "") or tableName.upper(),
		description=root.get("@adtcore:description", "") or "",
		language=root.get("@adtcore:language", "") or "",
		version=root.get("@adtcore:version", "") or "",
		createdAt=root.get("@adtcore:createdAt", "") or "",
		createdBy=root.get("@adtcore:createdBy", "") or "",
		changedAt=root.get("@adtcore:changedAt", "") or "",
		changedBy=root.get("@adtcore:changedBy", "") or "",
		dataClassCategory=root.get("ts:dataClassCategory", "") or "",
		sizeCategory=root.get("ts:sizeCategory", "") or "",
		bufferingAllowed=buffering.get("ts:allowed", "") or "",
		bufferingType=buffering.get("ts:type", "") or "",
		bufferingAreaKeyFields=_parse_int(buffering.get("ts:areaKeyFields")),
		storageType=root.get("ts:storageType", "") or "",
		sharingType=root.get("ts:sharingType", "") or "",
		loadUnit=root.get("ts:loadUnit", "") or "",
		translationValue=translation.get("@ts:value", "") or "",
		translationGranularity=translation.get("@ts:granularity", "") or "",
		translationIsVisible=_parse_bool(translation.get("@ts:isVisible")),
		translationIsEditable=_parse_bool(translation.get("@ts:isEditable")),
		loggingEnabled=_parse_bool(root.get("ts:loggingEnabled")),
		supportsLoggingAssessment=_parse_bool(root.get("ts:supportsLoggingAssessment")),
		etag=response.headers.get("ETag", "") or "",
		lastModified=response.headers.get("Last-Modified", "") or ""
	)


def _get_ddic_table_db_settings_xml(systemId: str, tableName: str):
	system_config = get_system_config(systemId)
	url = f"{system_config.server}/sap/bc/adt/ddic/db/settings/{tableName.lower()}"
	headers = {
		"Accept": "application/vnd.sap.adt.table.settings.v1+xml, application/vnd.sap.adt.table.settings.v2+xml",
		"Cache-Control": "no-cache"
	}
	return get_session(systemId).get(url, headers=headers)


def _build_db_settings_update_payload(current_xml: str, request: DdicTableDbSettingsUpdateRequest) -> str:
	payload = xmltodict.parse(current_xml)
	root = payload.get("ts:tableSettings", {})
	buffering = root.setdefault("ts:buffering", {})

	_set_if_provided(root, "ts:dataClassCategory", request.dataClassCategory)
	_set_if_provided(root, "ts:sizeCategory", request.sizeCategory)
	_set_if_provided(buffering, "ts:allowed", request.bufferingAllowed)
	_set_if_provided(buffering, "ts:type", request.bufferingType)
	_set_if_provided(buffering, "ts:areaKeyFields", str(request.bufferingAreaKeyFields) if request.bufferingAreaKeyFields is not None else None)
	_set_if_provided(root, "ts:storageType", request.storageType)
	_set_if_provided(root, "ts:sharingType", request.sharingType)
	_set_if_provided(root, "ts:loadUnit", request.loadUnit)
	_set_if_provided(root, "ts:loggingEnabled", str(request.loggingEnabled).lower() if request.loggingEnabled is not None else None)

	return xmltodict.unparse(payload, pretty=False)


def parse_ddic_table_db_settings_read_response(systemId: str, tableName: str, response) -> DdicTableDbSettingsReadResponse:
	try:
		output = _parse_db_settings_response(systemId, tableName, response)
		return DdicTableDbSettingsReadResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table database settings read successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableDbSettingsReadResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC table database settings response: {str(e)}",
			"data": None
		})


def parse_ddic_table_db_settings_lock_response(response) -> DdicTableDbSettingsLockResponse:
	try:
		data_dict = xmltodict.parse(response.text)
		data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {})
		output = DdicTableDbSettingsLockOutput(
			lockHandle=data_root.get("LOCK_HANDLE", "") or "",
			corrNr=data_root.get("CORRNR", "") or "",
			corrUser=data_root.get("CORRUSER", "") or "",
			corrText=data_root.get("CORRTEXT", "") or "",
			isLocal=_parse_bool(data_root.get("IS_LOCAL")),
			isLinkUp=_parse_bool(data_root.get("IS_LINK_UP")),
			modificationSupport=data_root.get("MODIFICATION_SUPPORT", "") or "",
			scopeMessages=data_root.get("SCOPE_MESSAGES", "") or ""
		)
		return DdicTableDbSettingsLockResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table database settings locked successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableDbSettingsLockResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the DDIC table database settings lock response: {str(e)}",
			"data": None
		})


def call_ddic_table_db_settings_read(systemId: str, tableName: str) -> DdicTableDbSettingsReadResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableDbSettingsReadResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot read the DDIC table database settings because no SAP session is available: {error_msg}",
				"data": None
			})

		response = _get_ddic_table_db_settings_xml(systemId, tableName)
		if response.status_code != 200:
			return DdicTableDbSettingsReadResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table database settings read request: {response.text}",
				"data": None
			})

		return parse_ddic_table_db_settings_read_response(systemId, tableName, response)
	except Exception as e:
		return DdicTableDbSettingsReadResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while reading the DDIC table database settings: {str(e)}",
			"data": None
		})


def call_ddic_table_db_settings_read_raw_content(systemId: str, tableName: str) -> str:
	"""Read the raw ADT XML of DDIC table database settings."""
	is_logged_in, error_msg = ensure_login(systemId)
	if not is_logged_in:
		raise RuntimeError(f"Cannot read the raw DDIC table database settings because no SAP session is available: {error_msg}")

	response = _get_ddic_table_db_settings_xml(systemId, tableName)
	if response.status_code != 200:
		raise RuntimeError(f"ADT rejected the raw DDIC table database settings read request: {response.text}")

	return response.text


def call_ddic_table_db_settings_update(
	systemId: str,
	tableName: str,
	lockHandle: str,
	request: DdicTableDbSettingsUpdateRequest,
	transportNumber: str = "",
) -> DdicTableDbSettingsUpdateResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableDbSettingsUpdateResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the DDIC table database settings because no SAP session is available: {error_msg}",
				"data": None
			})

		current_response = _get_ddic_table_db_settings_xml(systemId, tableName)
		if current_response.status_code != 200:
			return DdicTableDbSettingsUpdateResponse.parse_obj({
				"result": False,
				"httpCode": current_response.status_code,
				"httpReason": current_response.reason,
				"message": f"Failed to read the current DDIC table database settings before updating them: {current_response.text}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/db/settings/{tableName.lower()}"
		headers = {
			"Content-Type": "application/vnd.sap.adt.table.settings.v2+xml; charset=utf-8",
			"Accept": "application/vnd.sap.adt.table.settings.v1+xml, application/vnd.sap.adt.table.settings.v2+xml"
		}
		params = {"lockHandle": lockHandle}
		if transportNumber:
			params["corrNr"] = transportNumber
		payload = _build_db_settings_update_payload(current_response.text, request)
		response = get_session(systemId).put(url, headers=headers, params=params, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return DdicTableDbSettingsUpdateResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table database settings update request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		output = _parse_db_settings_response(systemId, tableName, response)
		return DdicTableDbSettingsUpdateResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table database settings updated successfully.",
			"data": output
		})
	except Exception as e:
		return DdicTableDbSettingsUpdateResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the DDIC table database settings: {str(e)}",
			"data": None
		})


def call_ddic_table_db_settings_update_raw(
	systemId: str,
	tableName: str,
	lockHandle: str,
	rawXml: str,
	transportNumber: str = "",
) -> DdicTableDbSettingsUpdateResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableDbSettingsUpdateResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the DDIC table database settings because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/db/settings/{tableName.lower()}"
		headers = {
			"Content-Type": "application/vnd.sap.adt.table.settings.v2+xml; charset=utf-8",
			"Accept": "application/vnd.sap.adt.table.settings.v1+xml, application/vnd.sap.adt.table.settings.v2+xml"
		}
		params = {"lockHandle": lockHandle}
		if transportNumber:
			params["corrNr"] = transportNumber

		response = get_session(systemId).put(url, headers=headers, params=params, data=rawXml.encode("utf-8"))
		if response.status_code != 200:
			return DdicTableDbSettingsUpdateResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table database settings raw update request. For transportable packages, ensure that corrNr references a valid transport request: {response.text}",
				"data": None
			})

		output = _parse_db_settings_response(systemId, tableName, response)
		return DdicTableDbSettingsUpdateResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table database settings updated successfully from raw XML.",
			"data": output
		})
	except Exception as e:
		return DdicTableDbSettingsUpdateResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the DDIC table database settings from raw XML: {str(e)}",
			"data": None
		})


def call_ddic_table_db_settings_lock(systemId: str, tableName: str, accessMode: str = "MODIFY") -> DdicTableDbSettingsLockResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableDbSettingsLockResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot lock the DDIC table database settings because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/db/settings/{tableName.lower()}"
		headers = build_adt_headers(
			sessionType="stateful",
			extra={
				"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
			}
		)
		params = {"_action": "LOCK", "accessMode": accessMode}
		response = get_session(systemId).post(url, headers=headers, params=params)

		if response.status_code != 200:
			return DdicTableDbSettingsLockResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table database settings lock request: {response.text}",
				"data": None
			})

		return parse_ddic_table_db_settings_lock_response(response)
	except Exception as e:
		return DdicTableDbSettingsLockResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while locking the DDIC table database settings: {str(e)}",
			"data": None
		})


def call_ddic_table_db_settings_unlock(systemId: str, tableName: str, lockHandle: str) -> DdicTableDbSettingsUnlockResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DdicTableDbSettingsUnlockResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot unlock the DDIC table database settings because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/ddic/db/settings/{tableName.lower()}"
		headers = build_adt_headers(sessionType="stateful")
		params = {"_action": "UNLOCK", "lockHandle": lockHandle}
		response = get_session(systemId).post(url, headers=headers, params=params)

		if response.status_code != 200:
			return DdicTableDbSettingsUnlockResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the DDIC table database settings unlock request: {response.text}",
				"data": None
			})

		return DdicTableDbSettingsUnlockResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "DDIC table database settings unlocked successfully.",
			"data": None
		})
	except Exception as e:
		return DdicTableDbSettingsUnlockResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while unlocking the DDIC table database settings: {str(e)}",
			"data": None
		})
# endregion
