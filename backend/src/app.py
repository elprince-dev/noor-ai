from fastapi import FastAPI, HTTPException

from src.models.requests import AskRequest
from src.models.responses import AskResponse, SessionResponse, HealthResponse
from src.services.chat_service import ChatService
from src.config import config

app = FastAPI(
    title="Noor AI",
    description="Your light to Islamic knowledge",
    version="1.0.0",
)

chat_service = ChatService()


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """Ask an Islamic knowledge question."""
    try:
        return await chat_service.ask(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions", response_model=SessionResponse)
async def create_session():
    """Create a new conversation session."""
    return chat_service.create_session()


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="healthy", model=config.bedrock_model_id)
