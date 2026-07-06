from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage

from src.services.llm_service import LLMService
from src.services.memory_service import MemoryService
from src.prompts.islamic_qa import SYSTEM_PROMPT


class ConversationChain:
    """Builds and runs the conversational chain with DynamoDB-backed history.

    Conversation history is managed explicitly (load → invoke → persist) rather
    than via the deprecated RunnableWithMessageHistory wrapper. Each turn:
      1. loads prior messages for the session from DynamoDB,
      2. invokes prompt → model → parser with that history,
      3. appends the new human + AI messages back to DynamoDB.
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

    async def ask(self, question: str, session_id: str, school: str = "general") -> str:
        """Ask a question within a conversation session.

        Args:
            question: The user's question.
            session_id: Unique session identifier.
            school: Preferred school of thought.

        Returns:
            The assistant's response as a string.
        """
        history = MemoryService.get_history(session_id)
        past_messages = history.messages

        answer = await self._chain.ainvoke(
            {"question": question, "school": school, "history": past_messages}
        )

        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))
        return answer
