from dataclasses import dataclass

import boto3

from src.config import config


@dataclass(frozen=True)
class RetrievedChunk:
    """A single grounded result from the Knowledge Base.

    A clean domain object so the rest of the app never touches raw boto3
    response shapes. `citation` comes from ingestion-time metadata, so it is
    authoritative — the LLM quotes it rather than inventing references.
    """

    text: str
    citation: str
    source_type: str  # "quran" | "hadith"
    score: float


class RetrievalService:
    """Retrieves grounded passages from the Bedrock Knowledge Base.

    Single responsibility: turn a query string into a list of RetrievedChunk.
    Owns the bedrock-agent-runtime `retrieve` call and the mapping from the
    raw response into domain objects — nothing else.

    Singleton client so the connection is reused across Lambda invocations
    (same pattern as LLMService).
    """

    _client = None

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            cls._client = boto3.client(
                "bedrock-agent-runtime", region_name=config.bedrock_region
            )
        return cls._client

    @classmethod
    def retrieve(
        cls,
        query: str,
        source_type: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve the most relevant chunks for a query.

        Args:
            query: The search text (natural language, Arabic or English).
            source_type: Optional filter — "quran" or "hadith". None searches
                both. (Unused by plain RAG; the agentic tools will use it.)
            top_k: Max results; defaults to config.retrieval_top_k.

        Returns:
            RetrievedChunk list, ordered by relevance (highest score first).
        """
        vector_config: dict = {"numberOfResults": top_k or config.retrieval_top_k}
        if source_type:
            vector_config["filter"] = {
                "equals": {"key": "source_type", "value": source_type}
            }

        response = cls._get_client().retrieve(
            knowledgeBaseId=config.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": vector_config},
        )

        return [cls._to_chunk(r) for r in response.get("retrievalResults", [])]

    @staticmethod
    def _to_chunk(result: dict) -> RetrievedChunk:
        """Map one raw retrieval result into a RetrievedChunk."""
        metadata = result.get("metadata", {})
        return RetrievedChunk(
            text=result.get("content", {}).get("text", ""),
            citation=str(metadata.get("citation", "")),
            source_type=str(metadata.get("source_type", "")),
            score=float(result.get("score", 0.0)),
        )