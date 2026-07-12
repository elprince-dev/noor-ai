from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.services.agent_factory import AgentFactory
from src.services.llm_service import LLMService
from src.services.memory_service import MemoryService


class ConversationChain:
    """Runs the agentic RAG turn with DynamoDB-backed history.

    Each turn: load history → run the tool-calling agent (which decides when to
    search Quran/hadith) → stream the final answer → persist. The agent loop
    runs server-side; only the final answer tokens are streamed to the client
    (approach A), so the existing streaming contract is unchanged.
    """

    def __init__(self):
        self._agent = AgentFactory.get_agent()

    def _build_messages(self, question: str, school: str, past_messages: list):
        """Assemble the message list for the agent: school note + history + question."""
        messages: list = []
        if school and school != "general":
            messages.append(
                SystemMessage(content=f"The user's preferred madhab is {school}. "
                                      f"Lead with that school's position.")
            )
        messages.extend(past_messages)
        messages.append(HumanMessage(content=question))
        return messages

    async def ask(self, question: str, session_id: str, school: str = "general") -> str:
        """Ask a question and return the full answer (non-streaming)."""
        history = MemoryService.get_history(session_id)
        messages = self._build_messages(question, school, history.messages)

        result = await self._agent.ainvoke({"messages": messages})
        answer = result["messages"][-1].content

        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))
        return answer

    async def astream(self, question: str, session_id: str, school: str = "general"):
        """Run the agent and stream only the final answer token-by-token."""
        history = MemoryService.get_history(session_id)
        messages = self._build_messages(question, school, history.messages)

        parts: list[str] = []
        # stream_mode="messages" yields (message_chunk, metadata) tuples for
        # every LLM token across the loop. We forward only assistant answer
        # text and drop tool-call / tool-result chunks so the client sees just
        # the final answer streaming in.
        async for chunk, metadata in self._agent.astream(
            {"messages": messages}, stream_mode="messages"
        ):
            # Skip tokens emitted while the model is calling tools; only the
            # final answer node should reach the user.
            if metadata.get("langgraph_node") != "model":
                continue
            text = LLMService.extract_text(getattr(chunk, "content", None))
            if not text:
                continue
            parts.append(text)
            yield text

        answer = "".join(parts)
        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))