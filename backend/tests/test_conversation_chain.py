"""Tests for ConversationChain — the agentic RAG orchestration wiring."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def _make_chunk(content):
    """Message chunk stub with the given content payload."""
    chunk = MagicMock()
    chunk.content = content
    return chunk


class TestConversationChain:
    @pytest.mark.asyncio
    @patch("src.chains.conversation.MemoryService")
    @patch("src.chains.conversation.AgentFactory")
    async def test_ask_runs_agent_and_persists_turn(self, mock_factory, mock_memory):
        # Agent returns a final assistant message.
        agent = MagicMock()
        agent.ainvoke = AsyncMock(
            return_value={
                "messages": [AIMessage(content="Intentions matter [Sahih al-Bukhari 1].")]
            }
        )
        mock_factory.get_agent.return_value = agent
        # History is an in-memory stub.
        history = MagicMock()
        history.messages = []
        mock_memory.get_history.return_value = history

        from src.chains.conversation import ConversationChain

        chain = ConversationChain()
        answer = await chain.ask("What is the reward of deeds based on?", "sess-1")

        # 1. the agent was invoked with the user question as the last message
        call_input = agent.ainvoke.call_args[0][0]
        assert call_input["messages"][-1].content == "What is the reward of deeds based on?"
        # 2. the turn was persisted (human + AI messages)
        assert history.add_message.call_count == 2
        assert answer == "Intentions matter [Sahih al-Bukhari 1]."

    @pytest.mark.asyncio
    @patch("src.chains.conversation.MemoryService")
    @patch("src.chains.conversation.AgentFactory")
    async def test_astream_yields_agent_events(self, mock_factory, mock_memory):
        # A turn with pre-tool preamble, one tool call, then the final answer
        # (Converse content-block format). Preamble streams to the client but
        # must be discarded from the persisted answer.
        events = [
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": _make_chunk([{"type": "text", "text": "Let me check. "}])},
            },
            {
                "event": "on_tool_start",
                "run_id": "run-1",
                "name": "search_hadith",
                "data": {"input": {"query": "intentions"}},
            },
            {
                "event": "on_tool_end",
                "run_id": "run-1",
                "name": "search_hadith",
                "data": {"output": "Actions are judged by intentions.\n\nSecond chunk."},
            },
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": _make_chunk([{"type": "text", "text": "Intentions "}])},
            },
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": _make_chunk([{"type": "text", "text": "matter."}])},
            },
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": _make_chunk([{"type": "tool_use", "id": "t1"}])},
            },
        ]

        async def fake_astream_events(*args, **kwargs):
            for event in events:
                yield event

        agent = MagicMock()
        agent.astream_events = fake_astream_events
        mock_factory.get_agent.return_value = agent
        history = MagicMock()
        history.messages = []
        mock_memory.get_history.return_value = history

        from src.chains.conversation import ConversationChain

        chain = ConversationChain()
        out = [e async for e in chain.astream("What matters?", "sess-1")]

        # 1. structured event sequence: preamble token, tool start/end,
        #    answer tokens, done. Non-text chunks yield nothing.
        assert [e.type for e in out] == [
            "token", "tool_start", "tool_end", "token", "token", "done",
        ]
        assert out[0].data["text"] == "Let me check. "
        assert out[1].data == {"id": "run-1", "tool": "search_hadith", "query": "intentions"}
        assert out[2].data["tool"] == "search_hadith"
        assert out[2].data["count"] == 2  # two chunks joined by \n\n
        assert [e.data["text"] for e in out[3:5]] == ["Intentions ", "matter."]
        # 2. persisted answer excludes the pre-tool preamble
        assert history.add_message.call_count == 2
        persisted_ai = history.add_message.call_args_list[1][0][0]
        assert persisted_ai.content == "Intentions matter."

    @pytest.mark.asyncio
    @patch("src.chains.conversation.MemoryService")
    @patch("src.chains.conversation.AgentFactory")
    async def test_school_preference_prepends_system_message(
        self, mock_factory, mock_memory
    ):
        agent = MagicMock()
        agent.ainvoke = AsyncMock(
            return_value={"messages": [AIMessage(content="Answer.")]}
        )
        mock_factory.get_agent.return_value = agent
        history = MagicMock()
        history.messages = [HumanMessage(content="earlier"), AIMessage(content="turn")]
        mock_memory.get_history.return_value = history

        from src.chains.conversation import ConversationChain

        chain = ConversationChain()
        await chain.ask("Follow-up?", "sess-1", school="hanafi")

        messages = agent.ainvoke.call_args[0][0]["messages"]
        # school note first, then history, then the new question
        assert isinstance(messages[0], SystemMessage)
        assert "hanafi" in messages[0].content
        assert messages[1].content == "earlier"
        assert messages[-1].content == "Follow-up?"
