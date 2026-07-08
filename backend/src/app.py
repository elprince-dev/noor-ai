from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.models.requests import AskRequest
from src.models.responses import SessionResponse, HealthResponse
from src.services.chat_service import ChatService
from src.config import config

app = FastAPI(
    title="Noor AI",
    description="Your light to Islamic knowledge",
    version="1.0.0",
)

# Public demo API. In production it's same-origin behind CloudFront, so CORS
# only matters for local dev (frontend on :3000 → backend on :8000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# All routes live under /api so the path is identical across local dev,
# the Lambda Function URL, and CloudFront (no prefix rewriting needed).
router = APIRouter(prefix="/api")

chat_service = ChatService()


@router.post("/ask")
async def ask(request: AskRequest):
    """Ask an Islamic knowledge question. Streams the answer token-by-token."""
    stream = chat_service.ask_stream(request)

    # Pull the first token eagerly so pre-stream failures (e.g. Bedrock access
    # errors) surface as a proper 500 instead of a broken 200 stream.
    try:
        first = await stream.__anext__()
    except StopAsyncIteration:
        first = ""
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def token_stream():
        yield first
        async for token in stream:
            yield token

    return StreamingResponse(token_stream(), media_type="text/plain; charset=utf-8")


@router.post("/sessions", response_model=SessionResponse)
async def create_session():
    """Create a new conversation session."""
    return chat_service.create_session()


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="healthy", model=config.bedrock_model_id)


app.include_router(router)
