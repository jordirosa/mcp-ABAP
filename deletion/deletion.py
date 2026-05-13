from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
import configuration
from generics import ApiResponse
from connection.connection import ensure_login


# region Deletion
class DeletionDeleteOutput(BaseModel):
	"""Normalized result of a generic ADT delete operation."""
	uri: str = Field(..., description="ADT URI of the object targeted by the delete request.")
	type: str = Field(default="", description="ADT object type of the deleted object.")
	name: str = Field(default="", description="Technical name of the deleted object.")
	packageName: str = Field(default="", description="Package that contained the deleted object.")
	isDeleted: bool = Field(default=False, description="Whether SAP reports that the object was deleted.")
	messageType: str = Field(default="", description="ADT message type returned for the delete operation.")
	messagePriority: int = Field(default=0, description="ADT message priority returned for the delete operation.")
	messageText: str = Field(default="", description="ADT message text returned for the delete operation.")


class DeletionDeleteResponse(ApiResponse[DeletionDeleteOutput]):
	"""Response model for generic ADT deletion."""


def _ensure_list(value):
	"""Normalize XML nodes that can appear either once or many times."""
	if value is None or value == "":
		return []
	if isinstance(value, list):
		return value
	return [value]


def _build_deletion_delete_payload(objectUri: str, transportNumber: str) -> str:
	"""Build XML payload for generic ADT deletion."""
	payload = {
		"del:deletionRequest": {
			"@xmlns:adtcore": "http://www.sap.com/adt/core",
			"@xmlns:del": "http://www.sap.com/adt/deletion",
			"del:object": {
				"@adtcore:uri": objectUri,
				"del:transportNumber": transportNumber
			}
		}
	}

	return xmltodict.unparse(payload, pretty=False)


def parse_deletion_delete_response(response) -> DeletionDeleteResponse:
	"""Parse XML response from generic ADT deletion API."""
	try:
		data_dict = xmltodict.parse(response.text)
		result_root = data_dict.get("del:deletionResult", {})
		object_root = _ensure_list(result_root.get("del:object"))[0] if _ensure_list(result_root.get("del:object")) else {}
		message_root = _ensure_list(object_root.get("del:message"))[0] if isinstance(object_root, dict) and _ensure_list(object_root.get("del:message")) else {}

		output = DeletionDeleteOutput(
			uri=object_root.get("@adtcore:uri", ""),
			type=object_root.get("@adtcore:type", ""),
			name=object_root.get("@adtcore:name", ""),
			packageName=object_root.get("@adtcore:packageName", ""),
			isDeleted=str(object_root.get("@del:isDeleted", "false")).lower() == "true",
			messageType=message_root.get("@del:type", ""),
			messagePriority=int(message_root.get("@del:priority", 0) or 0),
			messageText=message_root.get("del:text", "") or ""
		)

		return DeletionDeleteResponse.model_validate({
			"result": output.isDeleted,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Object deleted successfully." if output.isDeleted else "Delete request completed.",
			"data": output
		})

	except Exception as e:
		return DeletionDeleteResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the delete response: {str(e)}",
			"data": None
		})


def call_deletion_delete(systemId: str, objectUri: str, transportNumber: str = "") -> DeletionDeleteResponse:
	"""Delete an ADT object using the generic deletion endpoint."""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return DeletionDeleteResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot delete the object because no SAP session is available: {error_msg}",
				"data": None
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/deletion/delete"
		headers = {
			"Content-Type": "application/vnd.sap.adt.deletion.request.v1+xml",
			"Accept": "application/vnd.sap.adt.deletion.response.v1+xml"
		}
		payload = _build_deletion_delete_payload(
			objectUri=objectUri,
			transportNumber=transportNumber
		)

		response = get_session(systemId).post(url, headers=headers, data=payload.encode("utf-8"))

		if response.status_code != 200:
			return DeletionDeleteResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the delete request: {response.text}",
				"data": None
			})

		return parse_deletion_delete_response(response)

	except Exception as e:
		return DeletionDeleteResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while deleting the object: {str(e)}",
			"data": None
		})
# endregion
