import uuid

from src.chains.conversation import ConversationChain
from src.models.requests import AskRequest
from src.models.responses import AskResponse, SessionResponse


class ChatService:
    """Main service orchestrating chat interactions.

    This is the single entry point for the API layer. It delegates to
    the conversation chain and handles session management.
    """

    def __init__(self):
        self._conversation = ConversationChain()

    async def ask(self, request: AskRequest) -> AskResponse:
        """Process a user question and return the response.

        Args:
            request: The validated ask request.

        Returns:
            AskResponse with the answer and session ID.
        """
        answer = await self._conversation.ask(
            question=request.question,
            session_id=request.session_id,
            school=request.school,
        )
        return AskResponse(answer=answer, session_id=request.session_id)

    async def ask_stream(self, request: AskRequest):
        """Process a question and stream the answer token-by-token.

        Args:
            request: The validated ask request.

        Yields:
            Answer text chunks (str).
        """
        async for token in self._conversation.astream(
            question=request.question,
            session_id=request.session_id,
            school=request.school,
        ):
            yield token

    @staticmethod
    def create_session() -> SessionResponse:
        """Create a new conversation session.

        Returns:
            SessionResponse with a new unique session ID.
        """
        return SessionResponse(session_id=str(uuid.uuid4()))
