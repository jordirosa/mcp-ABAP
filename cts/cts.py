from pydantic import BaseModel, Field
import xmltodict

from configuration import APP_CONFIG
import configuration
from generics import ApiResponse
from connection.connection import ensure_login


# region CTS
class CtsTransportCheckOutput(BaseModel):
	"""Normalized result of an ADT transport check."""
	pgmid: str = Field(default="", description="SAP program ID returned by the transport check, such as R3TR.")
	object: str = Field(default="", description="SAP transport object type returned by the transport check, such as DOMA.")
	objectName: str = Field(default="", description="Technical object name returned by the transport check.")
	operation: str = Field(default="", description="Operation code checked by CTS, such as I for create or U for update.")
	devclass: str = Field(default="", description="Package evaluated by the transport check.")
	description: str = Field(default="", description="Package description returned by CTS.")
	resultCode: str = Field(default="", description="CTS result code returned by SAP.")
	recording: str = Field(default="", description="Recording mode returned by CTS.")
	existingRequestOnly: str = Field(default="", description="Whether CTS requires an existing request.")
	as4User: str = Field(default="", description="SAP user returned by CTS.")
	dlvUnit: str = Field(default="", description="Delivery unit returned by CTS.")
	namespace: str = Field(default="", description="Namespace returned by CTS.")
	tadirDevclass: str = Field(default="", description="Package stored in TADIR for the object.")
	uri: str = Field(default="", description="ADT URI checked by CTS.")
	requiresTransport: bool = Field(default=False, description="Whether the object should be assigned to a transport request.")


class CtsTransportCheckResponse(ApiResponse[CtsTransportCheckOutput]):
	"""Response model for CTS transport check."""


class CtsTransportCreateOutput(BaseModel):
	"""Result of creating a transport request through ADT."""
	transportNumber: str = Field(default="", description="Created transport request number.")
	severity: str = Field(default="", description="Severity returned by SAP for the creation result.")
	shortText: str = Field(default="", description="Short message returned by SAP.")
	longText: str = Field(default="", description="Long message returned by SAP.")


class CtsTransportCreateResponse(ApiResponse[CtsTransportCreateOutput]):
	"""Response model for transport request creation."""


def _build_cts_transport_check_payload(
	objectUri: str,
	packageName: str,
	operation: str,
	superPackage: str = "",
	recordChanges: str = "",
) -> str:
	"""Build XML payload for the CTS transport check endpoint."""
	payload = {
		"asx:abap": {
			"@version": "1.0",
			"@xmlns:asx": "http://www.sap.com/abapxml",
			"asx:values": {
				"DATA": {
					"PGMID": "",
					"OBJECT": "",
					"OBJECTNAME": "",
					"DEVCLASS": packageName,
					"SUPER_PACKAGE": superPackage,
					"RECORD_CHANGES": recordChanges,
					"OPERATION": operation,
					"URI": objectUri
				}
			}
		}
	}

	return xmltodict.unparse(payload, pretty=False)


def _build_cts_transport_create_payload(
	packageName: str,
	requestText: str,
	objectUri: str,
	operation: str,
) -> str:
	"""Build XML payload for creating a transport request through ADT."""
	payload = {
		"asx:abap": {
			"@version": "1.0",
			"@xmlns:asx": "http://www.sap.com/abapxml",
			"asx:values": {
				"DATA": {
					"OPERATION": operation,
					"DEVCLASS": packageName,
					"REQUEST_TEXT": requestText,
					"REF": objectUri
				}
			}
		}
	}

	return xmltodict.unparse(payload, pretty=False)


def parse_cts_transport_check_response(response) -> CtsTransportCheckResponse:
	"""Parse XML response from the CTS transport check endpoint."""
	try:
		data_dict = xmltodict.parse(response.text)
		data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {})
		devclass = data_root.get("DEVCLASS", "") or ""
		requires_transport = devclass != "$TMP"

		output = CtsTransportCheckOutput(
			pgmid=data_root.get("PGMID", "") or "",
			object=data_root.get("OBJECT", "") or "",
			objectName=data_root.get("OBJECTNAME", "") or "",
			operation=data_root.get("OPERATION", "") or "",
			devclass=devclass,
			description=data_root.get("CTEXT", "") or "",
			resultCode=data_root.get("RESULT", "") or "",
			recording=data_root.get("RECORDING", "") or "",
			existingRequestOnly=data_root.get("EXISTING_REQ_ONLY", "") or "",
			as4User=data_root.get("AS4USER", "") or "",
			dlvUnit=data_root.get("DLVUNIT", "") or "",
			namespace=data_root.get("NAMESPACE", "") or "",
			tadirDevclass=data_root.get("TADIRDEVC", "") or "",
			uri=data_root.get("URI", "") or "",
			requiresTransport=requires_transport
		)

		return CtsTransportCheckResponse.parse_obj({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "CTS transport check completed successfully.",
			"data": output
		})

	except Exception as e:
		return CtsTransportCheckResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the CTS transport check response: {str(e)}",
			"data": None
		})


def parse_cts_transport_create_response(response) -> CtsTransportCreateResponse:
	"""Parse XML response from the CTS transport creation endpoint."""
	try:
		data_dict = xmltodict.parse(response.text)
		data_root = data_dict.get("asx:abap", {}).get("asx:values", {}).get("DATA", {})
		message_root = data_root.get("MESSAGE", {}) or {}

		output = CtsTransportCreateOutput(
			transportNumber=data_root.get("TRKORR", "") or "",
			severity=message_root.get("SEVERITY", "") or "",
			shortText=message_root.get("SHORT_TEXT", "") or "",
			longText=message_root.get("LONG_TEXT", "") or ""
		)

		return CtsTransportCreateResponse.parse_obj({
			"result": bool(output.transportNumber),
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request created successfully." if output.transportNumber else "Transport creation request completed.",
			"data": output
		})

	except Exception as e:
		return CtsTransportCreateResponse.parse_obj({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the transport creation response: {str(e)}",
			"data": None
		})


def call_cts_transport_check(
	objectUri: str,
	packageName: str,
	operation: str = "I",
	superPackage: str = "",
	recordChanges: str = "",
) -> CtsTransportCheckResponse:
	"""Check whether an object and package combination requires a transport request."""
	try:
		is_logged_in, error_msg = ensure_login()
		if not is_logged_in:
			return CtsTransportCheckResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot run the CTS transport check because no SAP session is available: {error_msg}",
				"data": None
			})

		url = f"{APP_CONFIG['server']}/sap/bc/adt/cts/transportchecks"
		headers = {
			"Content-Type": "application/vnd.sap.as+xml; charset=UTF-8; dataname=com.sap.adt.transport.service.checkData",
			"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.transport.service.checkData"
		}
		payload = _build_cts_transport_check_payload(
			objectUri=objectUri,
			packageName=packageName,
			operation=operation,
			superPackage=superPackage,
			recordChanges=recordChanges
		)

		response = configuration.SESSION.post(url, headers=headers, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return CtsTransportCheckResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the CTS transport check request: {response.text}",
				"data": None
			})

		return parse_cts_transport_check_response(response)

	except Exception as e:
		return CtsTransportCheckResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while running the CTS transport check: {str(e)}",
			"data": None
		})


def call_cts_transport_create(
	packageName: str,
	requestText: str,
	objectUri: str,
	operation: str = "I",
) -> CtsTransportCreateResponse:
	"""Create a transport request for a package and ADT object reference."""
	try:
		is_logged_in, error_msg = ensure_login()
		if not is_logged_in:
			return CtsTransportCreateResponse.parse_obj({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot create the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		url = f"{APP_CONFIG['server']}/sap/bc/adt/cts/transports"
		headers = {
			"Content-Type": "application/vnd.sap.as+xml; charset=UTF-8; dataname=com.sap.adt.CreateCorrectionRequest.v1",
			"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.CorrectionRequestResult, text/plain"
		}
		payload = _build_cts_transport_create_payload(
			packageName=packageName,
			requestText=requestText,
			objectUri=objectUri,
			operation=operation
		)

		response = configuration.SESSION.post(url, headers=headers, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return CtsTransportCreateResponse.parse_obj({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport creation request: {response.text}",
				"data": None
			})

		return parse_cts_transport_create_response(response)

	except Exception as e:
		return CtsTransportCreateResponse.parse_obj({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while creating the transport request: {str(e)}",
			"data": None
		})
# endregion
