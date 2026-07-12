"""Tests for ConversationChain — the RAG orchestration wiring."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.retrieval_service import RetrievedChunk


class TestConversationChain:
    @pytest.mark.asyncio
    @patch("src.chains.conversation.MemoryService")
    @patch("src.chains.conversation.RetrievalService")
    async def test_ask_retrieves_and_injects_context(
        self, mock_retrieval, mock_memory
    ):
        # Retrieval returns one grounded chunk.
        mock_retrieval.retrieve.return_value = [
            RetrievedChunk(
                text="Actions are judged by intentions.",
                citation="Sahih al-Bukhari 1",
                source_type="hadith",
                score=0.9,
            )
        ]
        # History is an in-memory stub.
        history = MagicMock()
        history.messages = []
        mock_memory.get_history.return_value = history

        from src.chains.conversation import ConversationChain

        chain = ConversationChain()
        # Replace the LCEL chain with an async stub capturing its input.
        chain._chain = MagicMock()
        chain._chain.ainvoke = AsyncMock(return_value="Intentions matter [Sahih al-Bukhari 1].")

        answer = await chain.ask("What is the reward of deeds based on?", "sess-1")

        # 1. retrieval was invoked with the question
        mock_retrieval.retrieve.assert_called_once()
        # 2. the formatted context reached the chain input
        call_input = chain._chain.ainvoke.call_args[0][0]
        assert "context" in call_input
        assert "Sahih al-Bukhari 1" in call_input["context"]
        assert call_input["question"] == "What is the reward of deeds based on?"
        # 3. the turn was persisted (human + AI messages)
        assert history.add_message.call_count == 2
        assert answer == "Intentions matter [Sahih al-Bukhari 1]."