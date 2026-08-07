import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.observability.instrumentation import AgentEventRecorder
from src.services.agent_factory import AgentFactory
from src.services.llm_service import LLMService
from src.services.memory_service import MemoryService
from src.streaming.agent_events import AgentEvent


def _count_results(output) -> int:
    """Count grounded chunks in a tool's output string (chunks joined by \\n\\n)."""
    content = getattr(output, "content", output)
    if not isinstance(content, str) or not content.strip():
        return 0
    if content.startswith("(No relevant"):
        return 0
    return content.count("\n\n") + 1


class ConversationChain:
    """Runs the agentic RAG turn with DynamoDB-backed history.

    Each turn: load history → run the tool-calling agent → stream structured
    events (tool start/end + answer tokens) → persist. Text emitted before a
    tool call is preamble and is discarded from the persisted answer; the same
    rule is applied client-side so only the final answer is shown.
    """

    def __init__(self):
        self._agent = AgentFactory.get_agent()
        self._recorder = AgentEventRecorder()

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
        answer = LLMService.extract_text(result["messages"][-1].content)

        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))
        return answer

    async def astream(self, question: str, session_id: str, school: str = "general"):
        """Run the agent and yield AgentEvents (tool steps + answer tokens)."""
        history = MemoryService.get_history(session_id)
        messages = self._build_messages(question, school, history.messages)

        answer_parts: list[str] = []
        tool_starts: dict[str, float] = {}

        async for event in self._agent.astream_events(
            {"messages": messages}, version="v2"
        ):
            self._recorder.on_event(event)
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                text = LLMService.extract_text(getattr(chunk, "content", None))
                if text:
                    answer_parts.append(text)
                    yield AgentEvent.token(text)

            elif kind == "on_tool_start":
                # Any answer text so far was pre-tool preamble — discard it.
                answer_parts.clear()
                run_id = event["run_id"]
                tool_starts[run_id] = time.monotonic()
                query = (event["data"].get("input") or {}).get("query", "")
                yield AgentEvent.tool_start(run_id, event["name"], query)

            elif kind == "on_tool_end":
                run_id = event["run_id"]
                start = tool_starts.pop(run_id, None)
                ms = int((time.monotonic() - start) * 1000) if start else 0
                count = _count_results(event["data"].get("output"))
                yield AgentEvent.tool_end(run_id, event["name"], ms, count)

        answer = "".join(answer_parts)
        self._recorder.on_complete(answer)
        history.add_message(HumanMessage(content=question))
        history.add_message(AIMessage(content=answer))
        yield AgentEvent.done()