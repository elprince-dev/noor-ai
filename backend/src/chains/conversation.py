from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage

from src.services.llm_service import LLMService
from src.services.memory_service import MemoryService
from src.services.retrieval_service import RetrievalService
from src.services.context_builder import ContextBuilder
from src.prompts.islamic_qa import SYSTEM_PROMPT


class ConversationChain:
    """Builds and runs the conversational RAG chain with DynamoDB-backed history.

    Each turn: retrieve grounded context → load history → invoke prompt → model
    → parser → persist. Retrieval is a single upfront call, so streaming is
    unaffected (retrieve, then stream the answer).
    """

    def __init__(self):
        self._chain = self._build_chain()

    def _build_chain(self):
        """Build the base chain: prompt → model → parser."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder("history"),
                ("human", "{question}"),
            ]
        )
        model = LLMService.get_model()
        return prompt | model | StrOutputParser()

    def _retrieve_context(self, question: str) -> str:
        """Retrieve grounded evidence and format it for the prompt."""
        chunks = RetrievalService.retrieve(question)
        return ContextBuilder.build(chunks)

    async def ask(self, question: str, session_id: str, school: str = "general") -> str:
        """Ask a question and return the full answer (non-streaming)."""
        context = self._retrieve_context(question)
        history = MemoryService.get_history(session_id)
        past_messages = history.messages

        answer = await self._chain.ainvoke(
            {
                "question": question,
                "school": school,
                "context": context,
                "history": past_messages,
            }
        )

        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))
        return answer

    async def astream(self, question: str, session_id: str, school: str = "general"):
        """Ask a question and stream the answer token-by-token."""
        context = self._retrieve_context(question)
        history = MemoryService.get_history(session_id)
        past_messages = history.messages

        chunks: list[str] = []
        async for chunk in self._chain.astream(
            {
                "question": question,
                "school": school,
                "context": context,
                "history": past_messages,
            }
        ):
            chunks.append(chunk)
            yield chunk

        answer = "".join(chunks)
        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))