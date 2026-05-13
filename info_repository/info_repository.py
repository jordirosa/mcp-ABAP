from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
import configuration
from generics import ApiResponse
from connection.connection import ensure_login

# region Info Repository - Search
class InfoRepositorySearchObjectReference(BaseModel):
	"""Model representing an object reference in the search results."""
	uri: str = Field(..., description="ADT URI of the repository object.")
	type: str = Field(..., description="SAP object type identifier returned by ADT.")
	name: str = Field(..., description="Technical name of the repository object.")
	packageName: str = Field(..., description="Package that contains the repository object.")
	description: str = Field(default="", description="Short description of the repository object.")

class InfoRepositorySearchOutput(BaseModel):
	"""Output model for info repository search API call."""
	objectReferences: list[InfoRepositorySearchObjectReference] = Field(default_factory=list, description="Repository objects returned by the search.")
	totalCount: int = Field(..., description="Number of objects returned in this response.")

class InfoRepositorySearchResponse(ApiResponse[InfoRepositorySearchOutput]):
	"""Response model for info repository search API call."""

def parse_info_repository_search_response(response) -> InfoRepositorySearchResponse:
	"""Parse XML response from info repository search API and return InfoRepositorySearchResponse object.
	
	Args:
		response: HTTP response object containing XML data
		
	Returns:
		InfoRepositorySearchResponse: Parsed response model
	"""
	try:
		data_dict = xmltodict.parse(response.text)
		
		object_references_root = data_dict.get('adtcore:objectReferences', {})
		raw_references = object_references_root.get('adtcore:objectReference', [])
		
		if not isinstance(raw_references, list):
			raw_references = [raw_references]
		
		object_references = []
		for ref in raw_references:
			object_references.append(InfoRepositorySearchObjectReference(
				uri=ref.get('@adtcore:uri', ''),
				type=ref.get('@adtcore:type', ''),
				name=ref.get('@adtcore:name', ''),
				packageName=ref.get('@adtcore:packageName', ''),
				description=ref.get('@adtcore:description', '')
			))
		
		output = InfoRepositorySearchOutput(
			objectReferences=object_references,
			totalCount=len(object_references)
		)
		
		return InfoRepositorySearchResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Repository search completed successfully.",
			"data": output
		})
		
	except Exception as e:
		return InfoRepositorySearchResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, 'status_code') else 500,
			"httpReason": response.reason if hasattr(response, 'reason') else "Internal Server Error",
			"message": f"Failed to parse the repository search response: {str(e)}",
			"data": None
		})

def call_info_repository_search(systemId: str, query: str, maxResults: int = 50, objectType: str = "") -> InfoRepositorySearchResponse:
	"""Search for objects in the SAP repository information system.

	Args:
		query (str): Search query pattern (e.g., 'Z*', 'PROGRAM_NAME')
		maxResults (int): Maximum number of results to retrieve (default: 50)
		objectType (str): Optional 4-character object type filter (e.g., 'PROG', 'CLAS', 'FUGR', 'TABL')

	Returns:
		InfoRepositorySearchResponse: Response model containing the search results.
	"""
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return InfoRepositorySearchResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot search the repository because no SAP session is available: {error_msg}",
				"data": None
			})

		# Build URL with query and maxResults
		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/repository/informationsystem/search?operation=quickSearch&query={query}&maxResults={maxResults}"
		
		# Add objectType parameter if provided
		if objectType:
			url += f"&objectType={objectType}"
		
		headers = {
			"Accept": "application/xml"
		}

		response = get_session(systemId).get(url, headers=headers)
		
		if response.status_code != 200:
			return InfoRepositorySearchResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the repository search request: {response.text}",
				"data": None
			})
		
		return parse_info_repository_search_response(response)
		
	except Exception as e:
		return InfoRepositorySearchResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while searching the repository: {str(e)}",
			"data": None
		})
# endregion
