from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
from generics import ApiResponse
from connection.connection import ensure_login


# region Activation
class ActivationObjectReference(BaseModel):
	"""Reference to one ADT object that should be activated."""
	uri: str = Field(..., description="ADT URI of the object to activate.")
	name: str = Field(default="", description="Technical name of the object to activate. If omitted, it is derived from the URI.")


class ActivationActivateRequest(BaseModel):
	"""Activation request for one or more ADT objects."""
	objects: list[ActivationObjectReference] = Field(..., description="One or more ADT object references to activate.")
	preauditRequested: bool = Field(True, description="Whether ADT should run the pre-audit checks before activation.")


class ActivationActivateOutput(BaseModel):
	"""Normalized result of a generic ADT activation request."""
	checkExecuted: bool = Field(default=False, description="Whether ADT executed checks before activation.")
	activationExecuted: bool = Field(default=False, description="Whether ADT executed the activation itself.")
	generationExecuted: bool = Field(default=False, description="Whether ADT executed generation after activation.")
	messages: list[dict] = Field(default_factory=list, description="Detailed activation messages returned by ADT, including errors and warnings.")


class ActivationActivateResponse(ApiResponse[ActivationActivateOutput]):
	"""Response model for generic ADT activation."""


def _derive_object_name(uri: str) -> str:
	"""Derive a technical object name from an ADT URI when the caller omits it."""
	return uri.rstrip("/").split("/")[-1].upper()


def _build_activation_activate_payload(request: ActivationActivateRequest) -> str:
	"""Build XML payload for generic ADT activation."""
	payload = {
		"adtcore:objectReferences": {
			"@xmlns:adtcore": "http://www.sap.com/adt/core",
			"adtcore:objectReference": [
				{
					"@adtcore:uri": item.uri,
					"@adtcore:name": item.name or _derive_object_name(item.uri)
				}
				for item in request.objects
			]
		}
	}

	return xmltodict.unparse(payload, pretty=False)


def parse_activation_activate_response(response) -> ActivationActivateResponse:
	"""Parse XML response from generic ADT activation API."""
	try:
		data_dict = xmltodict.parse(response.text)
		root = data_dict.get("chkl:messages", {}) or {}
		properties = root.get("chkl:properties", {}) or {}
		raw_messages = root.get("msg", [])
		if not isinstance(raw_messages, list):
			raw_messages = [raw_messages] if raw_messages else []

		parsed_messages = []
		has_errors = False

		for item in raw_messages:
			if not isinstance(item, dict):
				continue

			raw_short_text = item.get("shortText", {}) or {}
			raw_texts = raw_short_text.get("txt", [])
			if not isinstance(raw_texts, list):
				raw_texts = [raw_texts] if raw_texts else []
			texts = [text for text in raw_texts if isinstance(text, str) and text]
			message_type = item.get("@type", "") or ""

			if message_type in ("E", "A", "X"):
				has_errors = True

			parsed_messages.append({
				"type": message_type,
				"line": int(item.get("@line", 0) or 0),
				"objectDescription": item.get("@objDescr", "") or "",
				"href": item.get("@href", "") or "",
				"text": " ".join(texts).strip(),
				"texts": texts
			})

		output = ActivationActivateOutput(
			checkExecuted=str(properties.get("@checkExecuted", "false")).lower() == "true",
			activationExecuted=str(properties.get("@activationExecuted", "false")).lower() == "true",
			generationExecuted=str(properties.get("@generationExecuted", "false")).lower() == "true",
			messages=parsed_messages
		)

		return ActivationActivateResponse.parse_obj({
			"result": output.activationExecuted and not has_errors,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "ADT activation completed successfully." if output.activationExecuted and not has_errors else "ADT activation completed with messages.",
			"data": output
		})
	except Exception as e:
		return ActivationActivateResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the activation response: {str(e)}",
			"data": None
		})


def call_activation_activate(systemId: str, request: ActivationActivateRequest) -> ActivationActivateResponse:
	"""Activate one or more ADT objects through the generic activation endpoint."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return ActivationActivateResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot activate the object because no SAP session is available: {error_msg}",
				"data": None
			})

		if not request.objects:
			return ActivationActivateResponse.parse_obj({
				"result": False,
				"httpCode": 400,
				"httpReason": "Bad Request",
				"message": "Activation requires at least one ADT object reference.",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/activation"
		headers = {
			"Content-Type": "application/xml",
			"Accept": "application/xml"
		}
		params = {
			"method": "activate",
			"preauditRequested": str(request.preauditRequested).lower()
		}
		payload = _build_activation_activate_payload(request)

		response = get_session(systemId).post(url, headers=headers, params=params, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return ActivationActivateResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the activation request: {response.text}",
				"data": None
			})

		return parse_activation_activate_response(response)
	except Exception as e:
		return ActivationActivateResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while activating the object: {str(e)}",
			"data": None
		})
# endregion
