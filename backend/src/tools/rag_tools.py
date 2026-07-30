from langchain_core.tools import tool, BaseTool

from src.services.retrieval_service import RetrievalService
from src.services.context_builder import ContextBuilder


class RagToolset:
    """Builds the retrieval tools the agent can call.

    Thin adapter layer between the agent and RetrievalService: each tool
    translates an agent search request into a filtered RetrievalService call
    and formats the results with ContextBuilder (same bracketed-citation shape
    used everywhere else). Retrieval logic itself stays in RetrievalService.

    The RetrievalService is injected so the toolset is unit-testable with a
    mock and holds no global state.
    """

    def __init__(self, retriever: type[RetrievalService] = RetrievalService):
        self._retriever = retriever

    def as_tools(self) -> list[BaseTool]:
        """Return the tool objects to hand to create_agent."""
        return [self._build_search_quran(), self._build_search_hadith()]

    def _build_search_quran(self) -> BaseTool:
        retriever = self._retriever

        @tool
        def search_quran(query: str) -> str:
            """Search the Quran for verses relevant to a topic or question.

            Use this to find Quranic evidence. `query` should be a concise
            description of the concept you need (English or Arabic), e.g.
            "reward of patience" or "prohibition of intoxicants".
            Returns verses prefixed with their citation, e.g. [Quran 2:255].
            """
            chunks = retriever.retrieve(query, source_type="quran")
            return ContextBuilder.build(chunks)

        return search_quran

    def _build_search_hadith(self) -> BaseTool:
        retriever = self._retriever

        @tool
        def search_hadith(query: str) -> str:
            """Search Sahih al-Bukhari and Sahih Muslim for hadith relevant to
            a topic or question.

            Use this to find hadith evidence. `query` should be a concise
            description of the concept you need (English or Arabic), e.g.
            "actions by intentions" or "night prayer witr".
            Returns hadith prefixed with their citation, e.g.
            [Sahih al-Bukhari 1] or [Sahih Muslim 8].
            """
            chunks = retriever.retrieve(query, source_type="hadith")
            return ContextBuilder.build(chunks)

        return search_hadith