from urllib.parse import quote

from pydantic import BaseModel, Field
import xmltodict

from configuration import get_session, get_system_config
import configuration
from generics import ApiResponse
from connection.connection import ensure_login


def _ensure_list(value):
	if value is None:
		return []
	if isinstance(value, list):
		return value
	return [value]

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

# region Info Repository - Where-Used
USAGE_REFERENCES_NAMESPACE = "http://www.sap.com/adt/ris/usageReferences"
USAGE_REFERENCES_REQUEST_MIME = "application/vnd.sap.adt.repository.usagereferences.request.v1+xml"
USAGE_REFERENCES_RESULT_MIME = "application/vnd.sap.adt.repository.usagereferences.result.v1+xml"
USAGE_SNIPPETS_REQUEST_MIME = "application/vnd.sap.adt.repository.usagesnippets.request.v1+xml"
USAGE_SNIPPETS_RESULT_MIME = "application/vnd.sap.adt.repository.usagesnippets.result.v1+xml"


class InfoRepositoryUsageReferencesRequest(BaseModel):
	"""Source selection used by ADT to run a where-used search for one ABAP symbol."""

	sourceUri: str = Field(..., description="ADT source URI containing the selected ABAP symbol, usually ending in /source/main. Existing # fragments are ignored.")
	startLine: int = Field(..., ge=1, description="ADT 1-based line where the referenced ABAP symbol starts.")
	startColumn: int = Field(..., ge=1, description="ADT 1-based column where the referenced ABAP symbol starts.")
	endLine: int | None = Field(None, ge=1, description="ADT 1-based line where the referenced ABAP symbol ends. Defaults to startLine when omitted.")
	endColumn: int | None = Field(None, ge=1, description="ADT 1-based column where the referenced ABAP symbol ends. Defaults to startColumn when omitted; pass the full selected token range for accurate where-used resolution.")
	version: str = Field("active", description="Source version to search, matching ADT's URI query parameter. Defaults to active.")


class InfoRepositoryUsageSnippetIdentifier(BaseModel):
	"""Semantic ABAP object identifier returned by usageReferences and accepted by usageSnippets."""

	objectIdentifier: str = Field(..., description="ADT usage reference objectIdentifier, such as ABAPFullName;...;2.")
	optional: bool = Field(False, description="Whether ADT may ignore this identifier when resolving snippets.")


class InfoRepositoryUsageSnippetsRequest(BaseModel):
	"""Object identifiers used to retrieve source snippets for where-used results."""

	objectIdentifiers: list[InfoRepositoryUsageSnippetIdentifier] = Field(..., min_length=1, description="Usage reference identifiers returned by info_repository_usage_references.")


class InfoRepositoryUsageReferencedObject(BaseModel):
	"""One node from the ADT where-used reference tree."""

	uri: str = Field("", description="ADT URI of the referenced tree node.")
	parentUri: str = Field("", description="ADT URI of the parent tree node when available.")
	isResult: bool = Field(False, description="Whether this tree node is itself a search result.")
	canHaveChildren: bool = Field(False, description="Whether ADT reports that this node can be expanded.")
	usageInformation: str = Field("", description="Comma-separated ADT usage metadata, for example gradeDirect or includeProductive.")
	objectIdentifier: str = Field("", description="Semantic identifier used to request code snippets for this result node.")
	name: str = Field("", description="Technical name of the ADT object when returned.")
	type: str = Field("", description="ADT object type when returned.")
	responsible: str = Field("", description="Responsible user when returned.")
	packageName: str = Field("", description="Owning package name when returned.")
	packageUri: str = Field("", description="Owning package ADT URI when returned.")


class InfoRepositoryUsageReferencesOutput(BaseModel):
	"""Where-used reference tree returned by ADT."""

	numberOfResults: int = Field(0, description="Number of where-used results reported by ADT.")
	resultDescription: str = Field("", description="Human-readable description of the where-used search.")
	referencedObjectIdentifier: str = Field("", description="Semantic identifier of the ABAP symbol used as the search origin.")
	referencedObjects: list[InfoRepositoryUsageReferencedObject] = Field(default_factory=list, description="Tree nodes returned by ADT for the where-used result.")
	objectIdentifiers: list[str] = Field(default_factory=list, description="Snippet object identifiers extracted from referencedObjects.")


class InfoRepositoryUsageReferencesResponse(ApiResponse[InfoRepositoryUsageReferencesOutput]):
	"""Response model for the ADT where-used usageReferences endpoint."""


class InfoRepositoryUsageCodeSnippet(BaseModel):
	"""One code occurrence returned by ADT usageSnippets."""

	uri: str = Field("", description="ADT source URI pointing to the exact usage range.")
	matches: str = Field("", description="ADT match metadata, such as column range, access kind, and usage grade.")
	content: str = Field("", description="Single source line containing the usage.")
	description: str = Field("", description="Expanded source context and usage kind text returned by ADT.")


class InfoRepositoryUsageSnippetObject(BaseModel):
	"""Code snippets grouped by one usage reference objectIdentifier."""

	objectIdentifier: str = Field("", description="Usage reference objectIdentifier used to request these snippets.")
	codeSnippets: list[InfoRepositoryUsageCodeSnippet] = Field(default_factory=list, description="Source snippets for this objectIdentifier.")
	totalCount: int = Field(0, description="Number of snippets in this group.")


class InfoRepositoryUsageSnippetsOutput(BaseModel):
	"""Snippet groups returned by ADT for where-used results."""

	codeSnippetObjects: list[InfoRepositoryUsageSnippetObject] = Field(default_factory=list, description="Snippet groups returned by ADT.")
	totalCount: int = Field(0, description="Total number of snippets across all groups.")


class InfoRepositoryUsageSnippetsResponse(ApiResponse[InfoRepositoryUsageSnippetsOutput]):
	"""Response model for the ADT where-used usageSnippets endpoint."""


class InfoRepositoryWhereUsedOutput(BaseModel):
	"""Combined where-used references and snippets."""

	usageReferences: InfoRepositoryUsageReferencesOutput = Field(..., description="Reference tree returned by the usageReferences endpoint.")
	usageSnippets: InfoRepositoryUsageSnippetsOutput = Field(..., description="Code snippets returned by the usageSnippets endpoint.")


class InfoRepositoryWhereUsedResponse(ApiResponse[InfoRepositoryWhereUsedOutput]):
	"""Response model for a complete ADT where-used lookup."""


def _build_usage_reference_source_uri(request: InfoRepositoryUsageReferencesRequest) -> str:
	source_uri = str(request.sourceUri or "").strip()
	if not source_uri:
		raise ValueError("sourceUri is required.")

	base_uri = source_uri.split("#", 1)[0]
	if request.version and "version=" not in base_uri:
		separator = "&" if "?" in base_uri else "?"
		base_uri = f"{base_uri}{separator}version={request.version}"

	end_line = request.endLine if request.endLine is not None else request.startLine
	end_column = request.endColumn if request.endColumn is not None else request.startColumn
	return f"{base_uri}#start={request.startLine},{request.startColumn};end={end_line},{end_column}"


def _build_usage_references_payload() -> str:
	payload = {
		"usagereferences:usageReferenceRequest": {
			"@xmlns:usagereferences": USAGE_REFERENCES_NAMESPACE,
			"usagereferences:affectedObjects": None,
		}
	}
	return xmltodict.unparse(payload, pretty=True)


def _build_usage_snippets_payload(request: InfoRepositoryUsageSnippetsRequest) -> str:
	identifiers = [
		{
			"@optional": "true" if item.optional else "false",
			"#text": item.objectIdentifier,
		}
		for item in request.objectIdentifiers
	]
	payload = {
		"usagereferences:usageSnippetRequest": {
			"@xmlns:usagereferences": USAGE_REFERENCES_NAMESPACE,
			"usagereferences:objectIdentifiers": {
				"usagereferences:objectIdentifier": identifiers,
			},
			"usagereferences:affectedObjects": None,
		}
	}
	return xmltodict.unparse(payload, pretty=True)


def _parse_bool(value) -> bool:
	return str(value or "").lower() == "true"


def parse_info_repository_usage_references_response(response) -> InfoRepositoryUsageReferencesResponse:
	try:
		data_dict = xmltodict.parse(response.text)
		root = data_dict.get("usageReferences:usageReferenceResult", {}) or {}
		referenced_root = root.get("usageReferences:referencedObjects", {}) or {}
		raw_objects = _ensure_list(referenced_root.get("usageReferences:referencedObject", []))

		referenced_objects = []
		object_identifiers = []
		for raw in raw_objects:
			adt_object = raw.get("usageReferences:adtObject", {}) or {}
			package_ref = adt_object.get("adtcore:packageRef", {}) or {}
			object_identifier = str(raw.get("objectIdentifier", "") or "")
			if object_identifier:
				object_identifiers.append(object_identifier)

			referenced_objects.append(InfoRepositoryUsageReferencedObject(
				uri=raw.get("@uri", ""),
				parentUri=raw.get("@parentUri", ""),
				isResult=_parse_bool(raw.get("@isResult")),
				canHaveChildren=_parse_bool(raw.get("@canHaveChildren")),
				usageInformation=raw.get("@usageInformation", ""),
				objectIdentifier=object_identifier,
				name=adt_object.get("@adtcore:name", ""),
				type=adt_object.get("@adtcore:type", ""),
				responsible=adt_object.get("@adtcore:responsible", ""),
				packageName=package_ref.get("@adtcore:name", ""),
				packageUri=package_ref.get("@adtcore:uri", ""),
			))

		output = InfoRepositoryUsageReferencesOutput(
			numberOfResults=int(root.get("@numberOfResults", 0) or 0),
			resultDescription=root.get("@resultDescription", ""),
			referencedObjectIdentifier=root.get("@referencedObjectIdentifier", ""),
			referencedObjects=referenced_objects,
			objectIdentifiers=object_identifiers,
		)

		return InfoRepositoryUsageReferencesResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Usage references resolved successfully.",
			"data": output,
		})
	except Exception as exc:
		return InfoRepositoryUsageReferencesResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the usage references response: {str(exc)}",
			"data": None,
		})


def parse_info_repository_usage_snippets_response(response) -> InfoRepositoryUsageSnippetsResponse:
	try:
		data_dict = xmltodict.parse(response.text)
		root = data_dict.get("usageReferences:usageSnippetResult", {}) or {}
		objects_root = root.get("usageReferences:codeSnippetObjects", {}) or {}
		raw_objects = _ensure_list(objects_root.get("usageReferences:codeSnippetObject", []))

		snippet_objects = []
		total_count = 0
		for raw_object in raw_objects:
			snippets_root = raw_object.get("usageReferences:codeSnippets", {}) or {}
			raw_snippets = _ensure_list(snippets_root.get("usageReferences:codeSnippet", []))
			snippets = [
				InfoRepositoryUsageCodeSnippet(
					uri=raw_snippet.get("@uri", ""),
					matches=raw_snippet.get("@matches", ""),
					content=str(raw_snippet.get("content", "") or ""),
					description=str(raw_snippet.get("description", "") or ""),
				)
				for raw_snippet in raw_snippets
			]
			total_count += len(snippets)
			snippet_objects.append(InfoRepositoryUsageSnippetObject(
				objectIdentifier=str(raw_object.get("objectIdentifier", "") or ""),
				codeSnippets=snippets,
				totalCount=len(snippets),
			))

		output = InfoRepositoryUsageSnippetsOutput(
			codeSnippetObjects=snippet_objects,
			totalCount=total_count,
		)

		return InfoRepositoryUsageSnippetsResponse.model_validate({
			"result": True,
			"httpCode": response.status_code,
			"httpReason": response.reason,
			"message": "Usage snippets resolved successfully.",
			"data": output,
		})
	except Exception as exc:
		return InfoRepositoryUsageSnippetsResponse.model_validate({
			"result": False,
			"httpCode": response.status_code if hasattr(response, "status_code") else 500,
			"httpReason": response.reason if hasattr(response, "reason") else "Internal Server Error",
			"message": f"Failed to parse the usage snippets response: {str(exc)}",
			"data": None,
		})


def call_info_repository_usage_references(systemId: str, request: InfoRepositoryUsageReferencesRequest) -> InfoRepositoryUsageReferencesResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return InfoRepositoryUsageReferencesResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot resolve usage references because no SAP session is available: {error_msg}",
				"data": None,
			})

		source_uri = _build_usage_reference_source_uri(request)
		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/repository/informationsystem/usageReferences?uri={quote(source_uri, safe='')}"
		headers = {
			"Accept": USAGE_REFERENCES_RESULT_MIME,
			"Content-Type": USAGE_REFERENCES_REQUEST_MIME,
		}
		response = get_session(systemId).post(url, headers=headers, data=_build_usage_references_payload())

		if response.status_code != 200:
			return InfoRepositoryUsageReferencesResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the usage references request: {response.text}",
				"data": None,
			})

		return parse_info_repository_usage_references_response(response)
	except ValueError as exc:
		return InfoRepositoryUsageReferencesResponse.model_validate({
			"result": False,
			"httpCode": 400,
			"httpReason": "Bad Request",
			"message": str(exc),
			"data": None,
		})
	except Exception as exc:
		return InfoRepositoryUsageReferencesResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while resolving usage references: {str(exc)}",
			"data": None,
		})


def call_info_repository_usage_snippets(systemId: str, request: InfoRepositoryUsageSnippetsRequest) -> InfoRepositoryUsageSnippetsResponse:
	try:
		is_logged_in, error_msg = ensure_login(systemId)
		if not is_logged_in:
			return InfoRepositoryUsageSnippetsResponse.model_validate({
				"result": False,
				"httpCode": 401,
				"httpReason": "Unauthorized",
				"message": f"Cannot resolve usage snippets because no SAP session is available: {error_msg}",
				"data": None,
			})

		system_config = get_system_config(systemId)
		url = f"{system_config.server}/sap/bc/adt/repository/informationsystem/usageSnippets"
		headers = {
			"Accept": USAGE_SNIPPETS_RESULT_MIME,
			"Content-Type": USAGE_SNIPPETS_REQUEST_MIME,
		}
		response = get_session(systemId).post(url, headers=headers, data=_build_usage_snippets_payload(request))

		if response.status_code != 200:
			return InfoRepositoryUsageSnippetsResponse.model_validate({
				"result": False,
				"httpCode": response.status_code,
				"httpReason": response.reason,
				"message": f"ADT rejected the usage snippets request: {response.text}",
				"data": None,
			})

		return parse_info_repository_usage_snippets_response(response)
	except Exception as exc:
		return InfoRepositoryUsageSnippetsResponse.model_validate({
			"result": False,
			"httpCode": 500,
			"httpReason": "Internal Server Error",
			"message": f"Unexpected error while resolving usage snippets: {str(exc)}",
			"data": None,
		})


def call_info_repository_where_used(systemId: str, request: InfoRepositoryUsageReferencesRequest) -> InfoRepositoryWhereUsedResponse:
	usage_references_response = call_info_repository_usage_references(systemId, request)
	if not usage_references_response.result or usage_references_response.data is None:
		return InfoRepositoryWhereUsedResponse.model_validate({
			"result": False,
			"httpCode": usage_references_response.httpCode,
			"httpReason": usage_references_response.httpReason,
			"message": usage_references_response.message,
			"data": None,
		})

	object_identifiers = usage_references_response.data.objectIdentifiers
	if not object_identifiers:
		return InfoRepositoryWhereUsedResponse.model_validate({
			"result": True,
			"httpCode": usage_references_response.httpCode,
			"httpReason": usage_references_response.httpReason,
			"message": "Where-used search completed successfully. No snippet identifiers were returned.",
			"data": InfoRepositoryWhereUsedOutput(
				usageReferences=usage_references_response.data,
				usageSnippets=InfoRepositoryUsageSnippetsOutput(),
			),
		})

	snippets_request = InfoRepositoryUsageSnippetsRequest(
		objectIdentifiers=[
			InfoRepositoryUsageSnippetIdentifier(objectIdentifier=identifier)
			for identifier in object_identifiers
		]
	)
	usage_snippets_response = call_info_repository_usage_snippets(systemId, snippets_request)
	if not usage_snippets_response.result or usage_snippets_response.data is None:
		return InfoRepositoryWhereUsedResponse.model_validate({
			"result": False,
			"httpCode": usage_snippets_response.httpCode,
			"httpReason": usage_snippets_response.httpReason,
			"message": usage_snippets_response.message,
			"data": None,
		})

	return InfoRepositoryWhereUsedResponse.model_validate({
		"result": True,
		"httpCode": usage_snippets_response.httpCode,
		"httpReason": usage_snippets_response.httpReason,
		"message": "Where-used search completed successfully.",
		"data": InfoRepositoryWhereUsedOutput(
			usageReferences=usage_references_response.data,
			usageSnippets=usage_snippets_response.data,
		),
	})
# endregion
