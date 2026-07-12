from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.models.requests import AskRequest
from src.models.responses import SessionResponse, HealthResponse
from src.services.chat_service import ChatService
from src.config import config
from src.streaming.agent_events import AgentEvent

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
    """Ask an Islamic knowledge question. Streams NDJSON agent events."""
    stream = chat_service.ask_stream(request)

    # Pull the first event eagerly so pre-stream failures (e.g. Bedrock access
    # errors) surface as a proper 500 instead of a broken 200 stream.
    try:
        first = await stream.__anext__()
    except StopAsyncIteration:
        first = None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def event_stream():
        try:
            if first is not None:
                yield first.to_ndjson()
            async for event in stream:
                yield event.to_ndjson()
        except Exception as e:
            # Surface mid-stream failures as an error event the UI can show.
            yield AgentEvent.error(str(e)).to_ndjson()

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/sessions", response_model=SessionResponse)
async def create_session():
    """Create a new conversation session."""
    return chat_service.create_session()


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="healthy", model=config.bedrock_model_id)


app.include_router(router)
