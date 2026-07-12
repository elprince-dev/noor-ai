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
    async def test_astream_yields_only_model_text(self, mock_factory, mock_memory):
        # Stream mixes tool-node chunks, Converse content blocks (list), plain
        # strings, and non-text blocks. Only model-node text should surface.
        events = [
            (_make_chunk([{"type": "tool_use", "id": "t1"}]), {"langgraph_node": "model"}),
            (_make_chunk("tool output"), {"langgraph_node": "tools"}),
            (_make_chunk([{"type": "text", "text": "Intentions "}]), {"langgraph_node": "model"}),
            (_make_chunk([{"type": "text", "text": "matter."}]), {"langgraph_node": "model"}),
            (_make_chunk(""), {"langgraph_node": "model"}),
        ]

        async def fake_astream(*args, **kwargs):
            for event in events:
                yield event

        agent = MagicMock()
        agent.astream = fake_astream
        mock_factory.get_agent.return_value = agent
        history = MagicMock()
        history.messages = []
        mock_memory.get_history.return_value = history

        from src.chains.conversation import ConversationChain

        chain = ConversationChain()
        tokens = [t async for t in chain.astream("What matters?", "sess-1")]

        # 1. only the final-answer text chunks were streamed
        assert tokens == ["Intentions ", "matter."]
        # 2. the turn was persisted with the joined answer
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
