"""Tests for the chat service."""
import pytest
from unittest.mock import AsyncMock, patch

from src.models.requests import AskRequest
from src.services.chat_service import ChatService


class TestChatService:
    """Unit tests for ChatService."""

    def test_create_session_returns_uuid(self):
        response = ChatService.create_session()
        assert response.session_id is not None
        assert len(response.session_id) == 36  # UUID format

    @pytest.mark.asyncio
    @patch("src.chains.conversation.ConversationChain.ask")
    async def test_ask_returns_response(self, mock_ask):
        mock_ask.return_value = "Zakat is obligatory..."
        service = ChatService()

        request = AskRequest(
            question="What is zakat?",
            session_id="test-session",
            school="general",
        )
        response = await service.ask(request)

        assert response.answer == "Zakat is obligatory..."
        assert response.session_id == "test-session"
