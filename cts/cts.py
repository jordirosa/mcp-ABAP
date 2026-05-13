from pydantic import BaseModel, Field
import xmltodict
from urllib.parse import quote

from configuration import get_session, get_system_config
import configuration
from generics import ApiResponse, FileTransferResponse
from connection.connection import build_adt_headers, ensure_login
from utils import build_file_transfer_error, build_file_transfer_response, read_text_file, write_text_file


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


class CtsTransportDeleteOutput(BaseModel):
	"""Result of deleting one CTS transport request through ADT."""
	transportNumber: str = Field(default="", description="Deleted transport request number.")


class CtsTransportDeleteResponse(ApiResponse[CtsTransportDeleteOutput]):
	"""Response model for transport request deletion."""


class CtsTransportObject(BaseModel):
	"""One development object assigned to a CTS request or task."""
	pgmid: str = Field(default="", description="SAP program ID of the transported object, such as R3TR.")
	objectType: str = Field(default="", description="SAP transport object type, such as DEVC.")
	name: str = Field(default="", description="Technical name of the transported object.")
	workbenchType: str = Field(default="", description="Workbench object type returned by ADT, such as DEVC/K.")
	objectInfo: str = Field(default="", description="Human-readable object information returned by SAP.")
	position: str = Field(default="", description="Position of the object inside the request or task.")
	lockStatus: str = Field(default="", description="Lock status returned by SAP for the object.")
	uri: str = Field(default="", description="Reference URI returned by SAP for the transported object.")


class CtsTransportTask(BaseModel):
	"""One task nested under a CTS request."""
	transportNumber: str = Field(default="", description="Task transport number.")
	parentTransportNumber: str = Field(default="", description="Parent request number.")
	owner: str = Field(default="", description="Owner of the task.")
	description: str = Field(default="", description="Task description.")
	type: str = Field(default="", description="Task type returned by SAP.")
	status: str = Field(default="", description="Status code returned by SAP.")
	statusText: str = Field(default="", description="Human-readable status text.")
	uri: str = Field(default="", description="ADT URI of the task.")
	objects: list[CtsTransportObject] = Field(default_factory=list, description="Objects assigned to the task.")


class CtsTransportReadOutput(BaseModel):
	"""Normalized details of one CTS transport request."""
	transportNumber: str = Field(default="", description="Transport request number.")
	objectType: str = Field(default="", description="ADT object type of the root resource.")
	rootType: str = Field(default="", description="Root CTS object type returned by SAP.")
	description: str = Field(default="", description="Short description of the transport request.")
	owner: str = Field(default="", description="Owner of the transport request.")
	status: str = Field(default="", description="Status code returned by SAP.")
	statusText: str = Field(default="", description="Human-readable status text.")
	target: str = Field(default="", description="Target system or route returned by SAP.")
	targetDescription: str = Field(default="", description="Target description returned by SAP.")
	sourceClient: str = Field(default="", description="Source SAP client.")
	uri: str = Field(default="", description="ADT URI of the transport request.")
	etag: str = Field(default="", description="ETag returned by SAP for the request resource.")
	objects: list[CtsTransportObject] = Field(default_factory=list, description="Objects assigned directly to the transport request.")
	tasks: list[CtsTransportTask] = Field(default_factory=list, description="Tasks nested under the transport request.")


class CtsTransportReadResponse(ApiResponse[CtsTransportReadOutput]):
	"""Response model for reading one CTS transport request."""


class CtsTransportLockOutput(BaseModel):
	"""Lock metadata returned for one CTS transport request."""
	transportNumber: str = Field(default="", description="Transport request number.")
	uri: str = Field(default="", description="ADT URI of the transport request.")
	lockHandle: str = Field(default="", description="ADT lock handle required to update and unlock the transport request.")
	corrnr: str = Field(default="", description="Transport request number returned by SAP when present.")
	corruser: str = Field(default="", description="Transport owner returned by SAP when present.")
	corrtext: str = Field(default="", description="Transport description returned by SAP when present.")
	isLocal: bool = Field(default=False, description="Whether SAP reports the lock as local.")


class CtsTransportLockResponse(ApiResponse[CtsTransportLockOutput]):
	"""Response model for locking or unlocking one CTS transport request."""


class CtsTransportUpdateRequest(BaseModel):
	"""Editable metadata of one CTS transport request."""
	description: str = Field(..., description="Short description of the transport request.")
	longDescriptionLines: list[str] = Field(default_factory=list, description="Long description lines stored inside tm:long_desc.")


class CtsTransportUpdateOutput(BaseModel):
	"""Result of updating one CTS transport request."""
	transportNumber: str = Field(default="", description="Transport request number.")
	uri: str = Field(default="", description="ADT URI of the transport request.")
	etag: str = Field(default="", description="ETag returned by SAP after the update.")


class CtsTransportUpdateResponse(ApiResponse[CtsTransportUpdateOutput]):
	"""Response model for updating one CTS transport request."""


class CtsTransportRawReadOutput(BaseModel):
	"""Raw CTS transport organizer XML returned by SAP."""
	transportNumber: str = Field(default="", description="Transport request number.")
	uri: str = Field(default="", description="ADT URI of the transport request.")
	content: str = Field(default="", description="Raw XML content returned by SAP.")
	contentType: str = Field(default="", description="HTTP content type returned by SAP.")
	etag: str = Field(default="", description="ETag returned by SAP for the request resource.")


class CtsTransportRawReadResponse(ApiResponse[CtsTransportRawReadOutput]):
	"""Response model for reading one CTS transport request as raw XML."""


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


def _transport_request_uri(transportNumber: str) -> str:
	"""Return the ADT URI of one CTS transport request."""
	normalized_transport = str(transportNumber or "").strip().upper()
	if not normalized_transport:
		raise ValueError("transportNumber is required.")
	return f"/sap/bc/adt/cts/transportrequests/{normalized_transport}"


def _build_cts_transport_update_payload(
	current: CtsTransportReadOutput,
	request: CtsTransportUpdateRequest,
) -> str:
	"""Build the ADT XML payload required to update one CTS transport request."""
	request_root = {
		"@tm:desc": request.description,
		"@tm:number": current.transportNumber,
		"@tm:type": "K",
		"@tm:owner": current.owner,
		"@tm:status": current.status,
		"@tm:status_text": current.statusText,
		"@tm:uri": current.uri,
		"@tm:target": current.target,
		"@tm:target_desc": current.targetDescription,
		"@tm:cts_project": "",
		"@tm:cts_project_desc": "",
		"@tm:source_client": current.sourceClient,
		"@tm:lastchanged_timestamp": "",
		"@tm:parent": "",
		"tm:long_desc": {
			"tm:long_desc_line": [
				{"@tm:long_desc_text": line}
				for line in request.longDescriptionLines
			]
		} if request.longDescriptionLines else {"tm:long_desc_line": []},
		"tm:all_objects": {
			"tm:abap_object": [
				{
					"@tm:dummy_uri": obj.uri,
					"@tm:lock_status": obj.lockStatus,
					"@tm:name": obj.name,
					"@tm:obj_info": obj.objectInfo,
					"@tm:pgmid": obj.pgmid,
					"@tm:type": obj.objectType,
					"@tm:wbtype": obj.workbenchType,
					"@tm:position": obj.position,
					"@tm:img_activity": "",
				}
				for obj in current.objects
			]
		},
		"tm:task": [
			{
				"@tm:desc": task.description,
				"@tm:number": task.transportNumber,
				"@tm:type": task.type,
				"@tm:parent": task.parentTransportNumber,
				"@tm:owner": task.owner,
				"@tm:status": task.status,
				"@tm:status_text": task.statusText,
				"@tm:uri": task.uri,
				"@tm:source_client": current.sourceClient,
				"@tm:lastchanged_timestamp": "",
				"@tm:target": "",
				"@tm:target_desc": "",
				"@tm:cts_project": "",
				"@tm:cts_project_desc": "",
				"tm:long_desc": {},
				"tm:abap_object": [
					{
						"@tm:dummy_uri": obj.uri,
						"@tm:lock_status": obj.lockStatus,
						"@tm:name": obj.name,
						"@tm:obj_info": obj.objectInfo,
						"@tm:pgmid": obj.pgmid,
						"@tm:type": obj.objectType,
						"@tm:wbtype": obj.workbenchType,
						"@tm:position": obj.position,
						"@tm:img_activity": "",
					}
					for obj in task.objects
				],
			}
			for task in current.tasks
		],
	}

	payload = {
		"tm:root": {
			"@xmlns:adtcore": "http://www.sap.com/adt/core",
			"@xmlns:atom": "http://www.w3.org/2005/Atom",
			"@xmlns:tm": "http://www.sap.com/cts/adt/tm",
			"@adtcore:changedAt": "",
			"@adtcore:changedBy": current.owner,
			"@adtcore:createdBy": current.owner,
			"@adtcore:name": current.transportNumber,
			"@adtcore:type": current.objectType,
			"@tm:object_type": current.rootType,
			"tm:request": request_root,
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

		return CtsTransportCheckResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "CTS transport check completed successfully.",
			"data": output
		})

	except Exception as e:
		return CtsTransportCheckResponse.model_validate({
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

		return CtsTransportCreateResponse.model_validate({
			"result": bool(output.transportNumber),
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request created successfully." if output.transportNumber else "Transport creation request completed.",
			"data": output
		})
	except Exception as e:
		return CtsTransportCreateResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the transport creation response: {str(e)}",
			"data": None
		})


def _ensure_list(value):
	"""Normalize XML nodes that can appear once or many times."""
	if value is None or value == "":
		return []
	if isinstance(value, list):
		return value
	return [value]


def _parse_transport_object(node: dict | None) -> CtsTransportObject:
	"""Parse one CTS object node returned by the transport organizer service."""
	node = node or {}
	return CtsTransportObject(
		pgmid=str(node.get("@tm:pgmid", "") or ""),
		objectType=str(node.get("@tm:type", "") or ""),
		name=str(node.get("@tm:name", "") or ""),
		workbenchType=str(node.get("@tm:wbtype", "") or ""),
		objectInfo=str(node.get("@tm:obj_info", "") or ""),
		position=str(node.get("@tm:position", "") or ""),
		lockStatus=str(node.get("@tm:lock_status", "") or ""),
		uri=str(node.get("@tm:dummy_uri", "") or ""),
	)


def _parse_transport_task(node: dict | None) -> CtsTransportTask:
	"""Parse one CTS task node returned by the transport organizer service."""
	node = node or {}
	return CtsTransportTask(
		transportNumber=str(node.get("@tm:number", "") or ""),
		parentTransportNumber=str(node.get("@tm:parent", "") or ""),
		owner=str(node.get("@tm:owner", "") or ""),
		description=str(node.get("@tm:desc", "") or ""),
		type=str(node.get("@tm:type", "") or ""),
		status=str(node.get("@tm:status", "") or ""),
		statusText=str(node.get("@tm:status_text", "") or ""),
		uri=str(node.get("@tm:uri", "") or ""),
		objects=[_parse_transport_object(item) for item in _ensure_list(node.get("tm:abap_object"))],
	)


def parse_cts_transport_read_response(response) -> CtsTransportReadResponse:
	"""Parse XML response from the CTS transport read endpoint."""
	try:
		data_dict = xmltodict.parse(response.text)
		root = data_dict.get("tm:root", {}) or {}
		request = root.get("tm:request", {}) or {}
		all_objects = (request.get("tm:all_objects", {}) or {})

		output = CtsTransportReadOutput(
			transportNumber=str(request.get("@tm:number", "") or root.get("@adtcore:name", "") or ""),
			objectType=str(root.get("@adtcore:type", "") or ""),
			rootType=str(root.get("@tm:object_type", "") or ""),
			description=str(request.get("@tm:desc", "") or ""),
			owner=str(request.get("@tm:owner", "") or ""),
			status=str(request.get("@tm:status", "") or ""),
			statusText=str(request.get("@tm:status_text", "") or ""),
			target=str(request.get("@tm:target", "") or ""),
			targetDescription=str(request.get("@tm:target_desc", "") or ""),
			sourceClient=str(request.get("@tm:source_client", "") or ""),
			uri=str(request.get("@tm:uri", "") or ""),
			etag=response.headers.get("ETag", ""),
			objects=[_parse_transport_object(item) for item in _ensure_list(all_objects.get("tm:abap_object"))],
			tasks=[_parse_transport_task(item) for item in _ensure_list(request.get("tm:task"))],
		)

		return CtsTransportReadResponse.model_validate({
			"result": bool(output.transportNumber),
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request read successfully." if output.transportNumber else "Transport read request completed.",
			"data": output
		})

	except Exception as e:
		return CtsTransportReadResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the transport read response: {str(e)}",
			"data": None
		})


def call_cts_transport_check(
	systemId: str,
	objectUri: str,
	packageName: str,
	operation: str = "I",
	superPackage: str = "",
	recordChanges: str = "",
) -> CtsTransportCheckResponse:
	"""Check whether an object and package combination requires a transport request."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportCheckResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot run the CTS transport check because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/cts/transportchecks"
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

		response = get_session(systemId).post(url, headers=headers, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return CtsTransportCheckResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the CTS transport check request: {response.text}",
				"data": None
			})

		return parse_cts_transport_check_response(response)

	except Exception as e:
		return CtsTransportCheckResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while running the CTS transport check: {str(e)}",
			"data": None
		})


def call_cts_transport_create(
	systemId: str,
	packageName: str,
	requestText: str,
	objectUri: str,
	operation: str = "I",
) -> CtsTransportCreateResponse:
	"""Create a transport request for a package and ADT object reference."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportCreateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot create the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/cts/transports"
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

		response = get_session(systemId).post(url, headers=headers, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return CtsTransportCreateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport creation request: {response.text}",
				"data": None
			})

		return parse_cts_transport_create_response(response)

	except Exception as e:
		return CtsTransportCreateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while creating the transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_read(
	systemId: str,
	transportNumber: str,
) -> CtsTransportReadResponse:
	"""Read one CTS transport request through the ADT transport organizer endpoint."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportReadResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot read the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		normalized_transport = str(transportNumber or "").strip().upper()
		if not normalized_transport:
			raise ValueError("transportNumber is required.")

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/cts/transportrequests/{normalized_transport}"
		headers = {
			"Accept": "application/vnd.sap.adt.transportorganizer.v1+xml"
		}

		response = get_session(systemId).get(url, headers=headers)

		if response.status_code != 200:
			return CtsTransportReadResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport read request: {response.text}",
				"data": None
			})

		return parse_cts_transport_read_response(response)

	except ValueError as e:
		return CtsTransportReadResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportReadResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while reading the transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_read_raw(systemId: str, transportNumber: str) -> CtsTransportRawReadResponse:
	"""Read one CTS transport request as raw XML through the ADT transport organizer endpoint."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportRawReadResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot read the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		normalized_transport = str(transportNumber or "").strip().upper()
		if not normalized_transport:
			raise ValueError("transportNumber is required.")

		system_config = get_system_config(systemId)
		uri = _transport_request_uri(normalized_transport)
		response = get_session(systemId).get(
			f"{system_config.server}{uri}",
			headers={"Accept": "application/vnd.sap.adt.transportorganizer.v1+xml"},
		)

		if response.status_code != 200:
			return CtsTransportRawReadResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the raw transport read request: {response.text}",
				"data": None
			})

		return CtsTransportRawReadResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request read successfully.",
			"data": CtsTransportRawReadOutput(
				transportNumber=normalized_transport,
				uri=uri,
				content=response.text,
				contentType=response.headers.get("Content-Type", ""),
				etag=response.headers.get("ETag", ""),
			)
		})
	except ValueError as e:
		return CtsTransportRawReadResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportRawReadResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while reading the raw transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_lock(
	systemId: str,
	transportNumber: str,
) -> CtsTransportLockResponse:
	"""Lock one CTS transport request through the ADT lock action."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportLockResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot lock the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		uri = _transport_request_uri(transportNumber)
		system_config = get_system_config(systemId)
		response = get_session(systemId).post(
			f"{system_config.server}{uri}?_action=LOCK&accessMode=MODIFY",
			headers=build_adt_headers(
				sessionType="stateful",
				extra={
					"Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result;q=0.8, application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.lock.result2;q=0.9"
				},
			),
		)

		if response.status_code != 200:
			return CtsTransportLockResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport lock request: {response.text}",
				"data": None
			})

		data = (((xmltodict.parse(response.text).get("asx:abap", {}) or {}).get("asx:values", {}) or {}).get("DATA", {}) or {})
		lock_handle = str(data.get("LOCK_HANDLE", "") or "")
		if not lock_handle:
			raise ValueError("SAP did not return a lock handle for the transport request.")

		return CtsTransportLockResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request locked successfully.",
			"data": CtsTransportLockOutput(
				transportNumber=str(transportNumber or "").strip().upper(),
				uri=uri,
				lockHandle=lock_handle,
				corrnr=str(data.get("CORRNR", "") or ""),
				corruser=str(data.get("CORRUSER", "") or ""),
				corrtext=str(data.get("CORRTEXT", "") or ""),
				isLocal=str(data.get("IS_LOCAL", "") or "").upper() == "X",
			)
		})
	except ValueError as e:
		return CtsTransportLockResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportLockResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while locking the transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_unlock(
	systemId: str,
	transportNumber: str,
	lockHandle: str,
) -> CtsTransportLockResponse:
	"""Unlock one CTS transport request through the ADT unlock action."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportLockResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot unlock the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		uri = _transport_request_uri(transportNumber)
		normalized_lock_handle = str(lockHandle or "").strip()
		if not normalized_lock_handle:
			raise ValueError("lockHandle is required.")

		system_config = get_system_config(systemId)
		response = get_session(systemId).post(
			f"{system_config.server}{uri}?_action=UNLOCK&lockHandle={quote(normalized_lock_handle, safe='')}",
			headers=build_adt_headers(sessionType="stateful"),
		)

		if response.status_code != 200:
			return CtsTransportLockResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport unlock request: {response.text}",
				"data": None
			})

		return CtsTransportLockResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request unlocked successfully.",
			"data": CtsTransportLockOutput(
				transportNumber=str(transportNumber or "").strip().upper(),
				uri=uri,
				lockHandle=normalized_lock_handle,
			)
		})
	except ValueError as e:
		return CtsTransportLockResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportLockResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while unlocking the transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_update(
	systemId: str,
	transportNumber: str,
	request: CtsTransportUpdateRequest,
) -> CtsTransportUpdateResponse:
	"""Update one CTS transport request through the ADT transport organizer endpoint."""
	try:
		read_response = call_cts_transport_read(systemId, transportNumber)
		if not read_response.result or not read_response.data:
			return CtsTransportUpdateResponse.model_validate({
				"result": False,
				"httpCode": read_response.httpCode,
				"httpReason": read_response.httpReason,
				"message": read_response.message or "Failed to read the transport request before update.",
				"data": None
			})

		lock_response = call_cts_transport_lock(systemId, transportNumber)
		if not lock_response.result or not lock_response.data:
			return CtsTransportUpdateResponse.model_validate({
				"result": False,
				"httpCode": lock_response.httpCode,
				"httpReason": lock_response.httpReason,
				"message": lock_response.message or "Failed to lock the transport request.",
				"data": None
			})

		try:
			system_config = get_system_config(systemId)
			uri = _transport_request_uri(transportNumber)
			payload = _build_cts_transport_update_payload(read_response.data, request)
			response = get_session(systemId).put(
				f"{system_config.server}{uri}?lockHandle={quote(lock_response.data.lockHandle, safe='')}",
				headers={"Content-Type": "application/vnd.sap.adt.transportorganizer.v1+xml; charset=utf-8"},
				data=payload.encode("utf-8"),
			)
		finally:
			call_cts_transport_unlock(systemId, transportNumber, lock_response.data.lockHandle)

		if response.status_code != 200:
			return CtsTransportUpdateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport update request: {response.text}",
				"data": None
			})

		return CtsTransportUpdateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request updated successfully.",
			"data": CtsTransportUpdateOutput(
				transportNumber=str(transportNumber or "").strip().upper(),
				uri=uri,
				etag=response.headers.get("ETag", ""),
			)
		})
	except ValueError as e:
		return CtsTransportUpdateResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportUpdateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_update_raw(
	systemId: str,
	transportNumber: str,
	lockHandle: str,
	rawXml: str,
) -> CtsTransportUpdateResponse:
	"""Update one CTS transport request by uploading raw ADT XML."""
	try:
		normalized_transport = str(transportNumber or "").strip().upper()
		if not normalized_transport:
			raise ValueError("transportNumber is required.")
		normalized_lock_handle = str(lockHandle or "").strip()
		if not normalized_lock_handle:
			raise ValueError("lockHandle is required.")

		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportUpdateResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot update the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		uri = _transport_request_uri(normalized_transport)
		response = get_session(systemId).put(
			f"{system_config.server}{uri}?lockHandle={quote(normalized_lock_handle, safe='')}",
			headers={"Content-Type": "application/vnd.sap.adt.transportorganizer.v1+xml; charset=utf-8"},
			data=rawXml.encode("utf-8"),
		)

		if response.status_code != 200:
			return CtsTransportUpdateResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport raw update request: {response.text}",
				"data": None
			})

		return CtsTransportUpdateResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request updated successfully.",
			"data": CtsTransportUpdateOutput(
				transportNumber=normalized_transport,
				uri=uri,
				etag=response.headers.get("ETag", ""),
			)
		})
	except ValueError as e:
		return CtsTransportUpdateResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportUpdateResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while updating the raw transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_delete(
	systemId: str,
	transportNumber: str,
) -> CtsTransportDeleteResponse:
	"""Delete one CTS transport request through the ADT transport organizer endpoint."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return CtsTransportDeleteResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot delete the transport request because no SAP session is available: {error_msg}",
				"data": None
			})

		normalized_transport = str(transportNumber or "").strip().upper()
		if not normalized_transport:
			raise ValueError("transportNumber is required.")

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/cts/transportrequests/{normalized_transport}"
		headers = {
			"Accept": "application/vnd.sap.adt.transportorganizer.v1+xml"
		}

		response = get_session(systemId).delete(url, headers=headers)

		if response.status_code != 200:
			return CtsTransportDeleteResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the transport deletion request: {response.text}",
				"data": None
			})

		return CtsTransportDeleteResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Transport request deleted successfully.",
			"data": CtsTransportDeleteOutput(
				transportNumber=normalized_transport,
			)
		})

	except ValueError as e:
		return CtsTransportDeleteResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(e),
			"data": None
		})
	except Exception as e:
		return CtsTransportDeleteResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while deleting the transport request: {str(e)}",
			"data": None
		})


def call_cts_transport_read_to_file(systemId: str, transportNumber: str, filePath: str) -> FileTransferResponse:
	"""Download one CTS transport request as raw XML to a local file."""
	try:
		response = call_cts_transport_read_raw(systemId, transportNumber)
		if not response.result or not response.data:
			return build_file_transfer_error(
				response.message or "Failed to read the transport request.",
				response.httpCode or 500,
				response.httpReason or "Internal Server Error",
			)

		size_bytes = write_text_file(filePath, response.data.content)
		return build_file_transfer_response(
			filePath=filePath,
			uri=response.data.uri,
			mimeType=response.data.contentType or "application/vnd.sap.adt.transportorganizer.v1+xml",
			sizeBytes=size_bytes,
			message="Transport request downloaded to local file successfully.",
		)
	except ValueError as e:
		return build_file_transfer_error(str(e), 400, "Bad Request")
	except Exception as e:
		return build_file_transfer_error(f"Failed to download the transport request to file: {str(e)}")


def call_cts_transport_write_from_file(systemId: str, transportNumber: str, filePath: str) -> FileTransferResponse:
	"""Upload one CTS transport request from a local XML file."""
	try:
		content, size_bytes = read_text_file(filePath)
		lock_response = call_cts_transport_lock(systemId, transportNumber)
		if not lock_response.result or not lock_response.data:
			return build_file_transfer_error(
				lock_response.message or "Failed to lock the transport request.",
				lock_response.httpCode or 500,
				lock_response.httpReason or "Internal Server Error",
			)

		try:
			update_response = call_cts_transport_update_raw(
				systemId=systemId,
				transportNumber=transportNumber,
				lockHandle=lock_response.data.lockHandle,
				rawXml=content,
			)
		finally:
			call_cts_transport_unlock(systemId, transportNumber, lock_response.data.lockHandle)

		if not update_response.result or not update_response.data:
			return build_file_transfer_error(
				update_response.message or "Failed to upload the transport request from file.",
				update_response.httpCode or 500,
				update_response.httpReason or "Internal Server Error",
			)

		return build_file_transfer_response(
			filePath=filePath,
			uri=update_response.data.uri,
			mimeType="application/vnd.sap.adt.transportorganizer.v1+xml",
			sizeBytes=size_bytes,
			message="Transport request uploaded from local file successfully.",
		)
	except ValueError as e:
		return build_file_transfer_error(str(e), 400, "Bad Request")
	except Exception as e:
		return build_file_transfer_error(f"Failed to upload the transport request from file: {str(e)}")
# endregion
