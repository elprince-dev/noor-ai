"""Pipeline client protocols and production adapters (Req 6.1, 6.6).

The Eval_Harness talks to the RAG pipeline through two narrow protocols so
the `EvalRunner` (task 8.4) is testable with in-memory fakes while the CLI
composition root injects the production adapters below, which wrap existing
`src` code without modifying it (design §eval harness):

- `RetrievalClient.retrieve(question, top_k)` — one retrieval step. Returns a
  `RetrievalResult` carrying the ranked `(citation, score)` pairs the runner
  records per item (Req 6.3) *and* the `ContextBuilder`-formatted context
  block. The context rides along because generation and the judge need the
  chunk texts (Req 8.3), which the scored pairs alone cannot reconstruct.
- `GenerationClient.generate(question, context, prompt_version)` — one-shot
  answer generation from an already-formatted context block. No conversation
  memory, no session: each Golden_Item is fully independent (Req 6.1).

Both adapters hit *deployed* AWS resources (Knowledge Base, Bedrock) using
normal developer credentials when run from `backend/` (Req 6.6).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from src.config import config
from src.prompts.islamic_qa import PROMPT_VERSIONS
from src.services.context_builder import ContextBuilder
from src.services.llm_service import LLMService
from src.services.retrieval_service import RetrievalService

# One retrieved source: (citation aka Source_ID, relevance score), rank order
# preserved — the shape retrieval metrics and per-item results consume.
ScoredSource = tuple[str, float]


@dataclass(frozen=True)
class RetrievalResult:
    """Output of one retrieval step for one Golden_Item.

    `sources` is what the runner records and the retrieval metrics score;
    `context` is the prompt-ready evidence block ("[citation] text" lines)
    that generation consumes. `texts` carries the raw chunk texts aligned
    index-for-index with `sources`, so the runner can hand the judge each
    chunk labeled with its Source_ID (Req 8.1, 8.2) — the formatted context
    string alone cannot be split back into chunks reliably.
    """

    sources: list[ScoredSource]
    context: str
    texts: tuple[str, ...] = ()  # chunk texts, aligned with `sources`


class RetrievalClient(Protocol):
    """Retrieves ranked, scored sources for one question."""

    def retrieve(self, question: str, top_k: int) -> RetrievalResult: ...


class GenerationClient(Protocol):
    """Generates one answer from a question and a formatted context block."""

    def generate(self, question: str, context: str, prompt_version: str) -> str: ...


class SrcRetrievalClient:
    """Production adapter: delegates to the deployed Knowledge Base.

    Thin wrapper over `RetrievalService` — maps each `RetrievedChunk` to a
    `(citation, score)` pair (order preserved) and formats the context block
    with `ContextBuilder`, the exact shape production prompts use.
    """

    def retrieve(self, question: str, top_k: int) -> RetrievalResult:
        chunks = RetrievalService.retrieve(question, top_k=top_k)
        return RetrievalResult(
            sources=[(chunk.citation, chunk.score) for chunk in chunks],
            context=ContextBuilder.build(chunks),
            texts=tuple(chunk.text for chunk in chunks),
        )


class SrcGenerationClient:
    """Production adapter: one-shot `ChatBedrockConverse` answer generation.

    Deliberately bypasses the agent loop, MemoryService, and sessions: the
    system prompt comes from `PROMPT_VERSIONS[prompt_version]` and the
    retrieved evidence is supplied directly in the user turn, so every call
    is stateless and items stay independent (Req 6.1; design scope decision).
    Model construction mirrors `LLMService` (temperature 0, region from
    `src.config`), with the model ID injected from the Eval_Config.
    """

    def __init__(self, model_id: str) -> None:
        self._model = ChatBedrockConverse(
            model=model_id,
            region_name=config.bedrock_region,
            temperature=0,
            max_tokens=2048,
        )

    def generate(self, question: str, context: str, prompt_version: str) -> str:
        if prompt_version not in PROMPT_VERSIONS:
            raise ValueError(
                f"unknown prompt_version {prompt_version!r}; "
                f"known versions: {sorted(PROMPT_VERSIONS)}"
            )
        messages = [
            SystemMessage(content=PROMPT_VERSIONS[prompt_version]),
            HumanMessage(
                content=f"RETRIEVED CONTEXT:\n{context}\n\nQUESTION:\n{question}"
            ),
        ]
        response = self._model.invoke(messages)
        return LLMService.extract_text(response.content)
