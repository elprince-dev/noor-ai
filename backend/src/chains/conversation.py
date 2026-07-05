from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.output_parsers import StrOutputParser

from src.services.llm_service import LLMService
from src.services.memory_service import MemoryService
from src.prompts.islamic_qa import SYSTEM_PROMPT


class ConversationChain:
    """Builds and manages the conversational LangChain chain.

    Combines the system prompt, chat history, and user input into a single
    chain that maintains conversation context via DynamoDB.
    """

    def __init__(self):
        self._chain = self._build_chain()
        self._chain_with_history = self._wrap_with_history()

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

    def _wrap_with_history(self):
        """Wrap the chain with message history management."""
        return RunnableWithMessageHistory(
            self._chain,
            MemoryService.get_history,
            input_messages_key="question",
            history_messages_key="history",
        )

    async def ask(self, question: str, session_id: str, school: str = "general") -> str:
        """Ask a question within a conversation session.

        Args:
            question: The user's question.
            session_id: Unique session identifier.
            school: Preferred school of thought.

        Returns:
            The assistant's response as a string.
        """
        config = {"configurable": {"session_id": session_id}}
        return await self._chain_with_history.ainvoke(
            {"question": question, "school": school},
            config=config,
        )
