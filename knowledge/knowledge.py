import json
import importlib
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from generics import ApiResponse

class KnowledgeUpsertDocumentRequest(BaseModel):
    """One knowledge document to insert or update inside the local knowledge base."""

    relativePath: str = Field(..., description="Relative path of the document inside db/documents. Do not include the fixed documents root.")
    content: str = Field(..., description="Full textual content of the knowledge document to store.")
    title: str = Field("", description="Optional human-readable title of the document.")
    metadata: dict[str, object] = Field(default_factory=dict, description="Optional free-form JSON metadata to store together with the document.")


class KnowledgeUpsertDocumentOutput(BaseModel):
    """Result of inserting or updating one knowledge document."""

    relativePath: str = Field(..., description="Relative path of the stored document inside db/documents.")
    documentPath: str = Field(..., description="Absolute local path of the stored document.")
    metadataPath: str = Field(..., description="Absolute local path of the metadata sidecar JSON file.")
    created: bool = Field(..., description="Whether the document was created instead of updated.")
    chunkCount: int = Field(..., description="Number of chunks written to the vector index for this document.")
    embeddingModel: str = Field(..., description="Embedding model used to index the document.")
    collectionName: str = Field(..., description="Chroma collection used to store the document chunks.")


class KnowledgeUpsertDocumentResponse(ApiResponse[KnowledgeUpsertDocumentOutput]):
    """Response model for inserting or updating one knowledge document."""


class KnowledgeSearchResult(BaseModel):
    """One chunk returned by semantic knowledge search."""

    relativePath: str = Field(..., description="Relative path of the document inside db/documents.")
    title: str = Field("", description="Human-readable title of the document when available.")
    snippet: str = Field(..., description="Matching knowledge snippet returned by semantic search.")
    score: float = Field(..., description="Similarity score derived from the vector distance. Higher is better.")
    chunkIndex: int = Field(..., description="Chunk index inside the source document.")
    metadata: dict[str, object] = Field(default_factory=dict, description="Metadata stored with the document.")


class KnowledgeSearchOutput(BaseModel):
    """Semantic search results over the local knowledge base."""

    query: str = Field(..., description="Search text used for semantic retrieval.")
    totalCount: int = Field(..., description="Number of matching chunks returned.")
    embeddingModel: str = Field(..., description="Embedding model used for semantic retrieval.")
    collectionName: str = Field(..., description="Chroma collection used for semantic retrieval.")
    results: list[KnowledgeSearchResult] = Field(default_factory=list, description="Ordered semantic search results.")


class KnowledgeSearchResponse(ApiResponse[KnowledgeSearchOutput]):
    """Response model for semantic knowledge search."""


class KnowledgeGetDocumentOutput(BaseModel):
    """Full stored knowledge document together with its metadata."""

    relativePath: str = Field(..., description="Relative path of the document inside db/documents.")
    documentPath: str = Field(..., description="Absolute local path of the stored document.")
    metadataPath: str = Field(..., description="Absolute local path of the metadata sidecar JSON file.")
    title: str = Field("", description="Human-readable title of the document when available.")
    content: str = Field(..., description="Full textual content of the document.")
    metadata: dict[str, object] = Field(default_factory=dict, description="Stored free-form metadata of the document.")
    createdAt: str = Field("", description="UTC timestamp indicating when the document was first stored.")
    updatedAt: str = Field("", description="UTC timestamp indicating when the document was last updated.")
    embeddingModel: str = Field(..., description="Embedding model that indexed the document.")
    collectionName: str = Field(..., description="Chroma collection used to store the document chunks.")


class KnowledgeGetDocumentResponse(ApiResponse[KnowledgeGetDocumentOutput]):
    """Response model for loading one stored knowledge document."""


_EMBEDDER = None
_CHROMA_CLIENT = None
_CHROMADB_MODULE = None
_SENTENCE_TRANSFORMER_CLASS = None
KNOWLEDGE_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
KNOWLEDGE_COLLECTION_NAME = "knowledge_documents"
KNOWLEDGE_CHUNK_SIZE = 1200
KNOWLEDGE_CHUNK_OVERLAP = 150


def _get_chromadb_module():
    """Load the chromadb module lazily so the MCP can start quickly."""
    global _CHROMADB_MODULE
    if _CHROMADB_MODULE is None:
        try:
            _CHROMADB_MODULE = importlib.import_module("chromadb")
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "Missing knowledge-layer dependency: chromadb. Install it with pip before using knowledge tools."
            ) from exc
    return _CHROMADB_MODULE


def _get_sentence_transformer_class():
    """Load SentenceTransformer lazily so the MCP can start quickly."""
    global _SENTENCE_TRANSFORMER_CLASS
    if _SENTENCE_TRANSFORMER_CLASS is None:
        try:
            module = importlib.import_module("sentence_transformers")
            _SENTENCE_TRANSFORMER_CLASS = getattr(module, "SentenceTransformer")
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "Missing knowledge-layer dependency: sentence-transformers. Install it with pip before using knowledge tools."
            ) from exc
    return _SENTENCE_TRANSFORMER_CLASS


def _repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parent.parent


def _documents_root() -> Path:
    """Return the fixed root folder used for knowledge documents."""
    root = _repo_root() / "db" / "documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _chroma_root() -> Path:
    """Return the fixed root folder used for Chroma persistence."""
    root = _repo_root() / "db" / "chroma"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _embedding_model_name() -> str:
    """Return the fixed embedding model name used for compatible knowledge exchange."""
    return KNOWLEDGE_EMBEDDING_MODEL


def _collection_name() -> str:
    """Return the fixed Chroma collection name used for compatible knowledge exchange."""
    return KNOWLEDGE_COLLECTION_NAME


def _chunk_size() -> int:
    """Return the fixed chunk size in characters used for compatible knowledge exchange."""
    return KNOWLEDGE_CHUNK_SIZE


def _chunk_overlap() -> int:
    """Return the fixed chunk overlap in characters used for compatible knowledge exchange."""
    return KNOWLEDGE_CHUNK_OVERLAP


def _utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_relative_document_path(relative_path: str) -> tuple[str, Path]:
    """Validate and resolve one relative document path inside db/documents."""
    cleaned = str(relative_path or "").strip().replace("\\", "/")
    if not cleaned:
        raise ValueError("relativePath is required.")
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        raise ValueError("relativePath must be relative to db/documents and must not start with a slash.")

    target_path = (_documents_root() / cleaned).resolve()
    documents_root = _documents_root().resolve()
    if documents_root not in [target_path, *target_path.parents]:
        raise ValueError("relativePath must stay inside db/documents.")

    return cleaned, target_path


def _metadata_path_for_document(document_path: Path) -> Path:
    """Return the sidecar metadata file path for one stored document."""
    return document_path.with_name(document_path.name + ".meta.json")


def _load_document_metadata(document_path: Path) -> dict[str, object]:
    """Load the sidecar metadata of one document when it exists."""
    metadata_path = _metadata_path_for_document(document_path)
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _save_document_metadata(document_path: Path, payload: dict[str, object]) -> Path:
    """Persist the sidecar metadata of one document."""
    metadata_path = _metadata_path_for_document(document_path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata_path


def _split_text_into_chunks(text: str) -> list[str]:
    """Split one document into overlapping chunks suitable for embeddings."""
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    chunk_size = _chunk_size()
    overlap = min(_chunk_overlap(), chunk_size - 1)
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _get_embedder():
    """Load the configured embedding model lazily and reuse it across calls."""
    global _EMBEDDER
    if _EMBEDDER is None:
        sentence_transformer_class = _get_sentence_transformer_class()
        _EMBEDDER = sentence_transformer_class(_embedding_model_name(), trust_remote_code=True)
    return _EMBEDDER


def _get_chroma_client():
    """Create or reuse the persistent Chroma client."""
    global _CHROMA_CLIENT
    if _CHROMA_CLIENT is None:
        chromadb_module = _get_chromadb_module()
        _CHROMA_CLIENT = chromadb_module.PersistentClient(path=str(_chroma_root()))
    return _CHROMA_CLIENT


def _get_collection():
    """Create or reuse the configured Chroma collection and validate its embedding metadata."""
    client = _get_chroma_client()
    collection = client.get_or_create_collection(
        name=_collection_name(),
        metadata={
            "embedding_model": _embedding_model_name(),
        }
    )

    metadata = collection.metadata or {}
    existing_model = str(metadata.get("embedding_model", "") or "")
    if existing_model and existing_model != _embedding_model_name():
        raise RuntimeError(
            "The existing knowledge collection was created with a different embedding model "
            f"({existing_model}) than the configured one ({_embedding_model_name()})."
        )
    return collection


def _document_embedding_texts(chunks: list[str]) -> list[str]:
    """Prepare document chunks for the configured embedding model."""
    model_name = _embedding_model_name().lower()
    if "nomic" in model_name:
        return [f"search_document: {chunk}" for chunk in chunks]
    return chunks


def _query_embedding_text(text: str) -> str:
    """Prepare one search query for the configured embedding model."""
    model_name = _embedding_model_name().lower()
    if "nomic" in model_name:
        return f"search_query: {text}"
    return text


def _encode_texts(texts: list[str]) -> list[list[float]]:
    """Encode one or more texts into embeddings."""
    embedder = _get_embedder()
    embeddings = embedder.encode(texts, normalize_embeddings=True)
    return [list(map(float, embedding)) for embedding in embeddings]


def _upsert_chunks(relative_path: str, title: str, metadata: dict[str, object], content: str) -> int:
    """Reindex one document in Chroma by replacing all previous chunks for the same path."""
    collection = _get_collection()
    chunks = _split_text_into_chunks(content)
    collection.delete(where={"relative_path": relative_path})

    if not chunks:
        return 0

    embeddings = _encode_texts(_document_embedding_texts(chunks))
    ids = [f"{relative_path}::chunk::{index:04d}" for index in range(len(chunks))]
    metadatas = [
        {
            "relative_path": relative_path,
            "title": title,
            "chunk_index": index,
            "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        }
        for index in range(len(chunks))
    ]
    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(chunks)


def call_knowledge_upsert_document(request: KnowledgeUpsertDocumentRequest) -> KnowledgeUpsertDocumentResponse:
    """Insert or update one local knowledge document and index it in Chroma."""
    try:
        normalized_relative_path, document_path = _normalize_relative_document_path(request.relativePath)
        document_path.parent.mkdir(parents=True, exist_ok=True)
        existed_before = document_path.exists()
        previous_metadata = _load_document_metadata(document_path) if existed_before else {}

        document_path.write_text(request.content, encoding="utf-8")
        created_at = str(previous_metadata.get("createdAt", "") or _utc_now())
        updated_at = _utc_now()
        stored_metadata = {
            "title": request.title,
            "metadata": request.metadata,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "embeddingModel": _embedding_model_name(),
            "collectionName": _collection_name(),
            "relativePath": normalized_relative_path,
        }
        metadata_path = _save_document_metadata(document_path, stored_metadata)
        chunk_count = _upsert_chunks(
            normalized_relative_path,
            request.title,
            request.metadata,
            request.content,
        )

        return KnowledgeUpsertDocumentResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "Knowledge document stored and indexed successfully.",
            "data": KnowledgeUpsertDocumentOutput(
                relativePath=normalized_relative_path,
                documentPath=str(document_path),
                metadataPath=str(metadata_path),
                created=not existed_before,
                chunkCount=chunk_count,
                embeddingModel=_embedding_model_name(),
                collectionName=_collection_name(),
            ),
        })
    except ValueError as exc:
        return KnowledgeUpsertDocumentResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return KnowledgeUpsertDocumentResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to store the knowledge document: {str(exc)}",
            "data": None,
        })


def call_knowledge_search(query: str, limit: int = 5) -> KnowledgeSearchResponse:
    """Search the local knowledge base semantically through Chroma."""
    try:
        cleaned_query = str(query or "").strip()
        if not cleaned_query:
            raise ValueError("query is required.")
        normalized_limit = max(1, min(int(limit), 25))
        collection = _get_collection()
        query_embedding = _encode_texts([_query_embedding_text(cleaned_query)])[0]
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=normalized_limit,
            include=["documents", "metadatas", "distances"],
        )

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        items: list[KnowledgeSearchResult] = []
        for index, snippet in enumerate(documents):
            metadata_row = metadatas[index] if index < len(metadatas) else {}
            distance = float(distances[index]) if index < len(distances) else 0.0
            free_metadata_raw = str(metadata_row.get("metadata_json", "") or "")
            try:
                free_metadata = json.loads(free_metadata_raw) if free_metadata_raw else {}
            except Exception:
                free_metadata = {}

            items.append(KnowledgeSearchResult(
                relativePath=str(metadata_row.get("relative_path", "") or ""),
                title=str(metadata_row.get("title", "") or ""),
                snippet=str(snippet or ""),
                score=max(0.0, 1.0 - distance),
                chunkIndex=int(metadata_row.get("chunk_index", 0) or 0),
                metadata=free_metadata,
            ))

        return KnowledgeSearchResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "Knowledge search completed successfully.",
            "data": KnowledgeSearchOutput(
                query=cleaned_query,
                totalCount=len(items),
                embeddingModel=_embedding_model_name(),
                collectionName=_collection_name(),
                results=items,
            ),
        })
    except ValueError as exc:
        return KnowledgeSearchResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return KnowledgeSearchResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to search the knowledge base: {str(exc)}",
            "data": None,
        })


def call_knowledge_get_document(relativePath: str) -> KnowledgeGetDocumentResponse:
    """Load one stored knowledge document from db/documents."""
    try:
        normalized_relative_path, document_path = _normalize_relative_document_path(relativePath)
        if not document_path.exists():
            raise FileNotFoundError(f"The knowledge document '{normalized_relative_path}' does not exist.")

        metadata_payload = _load_document_metadata(document_path)
        metadata_path = _metadata_path_for_document(document_path)

        return KnowledgeGetDocumentResponse.parse_obj({
            "result": True,
            "httpCode": 200,
            "httpReason": "OK",
            "message": "Knowledge document loaded successfully.",
            "data": KnowledgeGetDocumentOutput(
                relativePath=normalized_relative_path,
                documentPath=str(document_path),
                metadataPath=str(metadata_path),
                title=str(metadata_payload.get("title", "") or ""),
                content=document_path.read_text(encoding="utf-8"),
                metadata=metadata_payload.get("metadata", {}) or {},
                createdAt=str(metadata_payload.get("createdAt", "") or ""),
                updatedAt=str(metadata_payload.get("updatedAt", "") or ""),
                embeddingModel=str(metadata_payload.get("embeddingModel", "") or _embedding_model_name()),
                collectionName=str(metadata_payload.get("collectionName", "") or _collection_name()),
            ),
        })
    except FileNotFoundError as exc:
        return KnowledgeGetDocumentResponse.parse_obj({
            "result": False,
            "httpCode": 404,
            "httpReason": "Not Found",
            "message": str(exc),
            "data": None,
        })
    except ValueError as exc:
        return KnowledgeGetDocumentResponse.parse_obj({
            "result": False,
            "httpCode": 400,
            "httpReason": "Bad Request",
            "message": str(exc),
            "data": None,
        })
    except Exception as exc:
        return KnowledgeGetDocumentResponse.parse_obj({
            "result": False,
            "httpCode": 500,
            "httpReason": "Internal Server Error",
            "message": f"Failed to load the knowledge document: {str(exc)}",
            "data": None,
        })
