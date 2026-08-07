from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.feedback.router import router as feedback_router
from src.models.requests import AskRequest
from src.models.responses import SessionResponse, HealthResponse
from src.observability.trace_context import TraceContext
from src.observability.wiring import build_trace_finalizer
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
finalizer = build_trace_finalizer()


@router.post("/ask")
async def ask(request: AskRequest):
    """Ask an Islamic knowledge question. Streams NDJSON agent events."""
    # The trace context must exist and be current before any pipeline step
    # runs (Req 1.1) so the retrieval/instrumentation hooks record into it —
    # including during the eager first-event pull below.
    ctx = TraceContext(query=request.question, session_id=request.session_id)
    ctx_token = ctx.activate()

    stream = chat_service.ask_stream(request)

    # Pull the first event eagerly so pre-stream failures (e.g. Bedrock access
    # errors) surface as a proper 500 instead of a broken 200 stream.
    try:
        first = await stream.__anext__()
    except StopAsyncIteration:
        first = None
    except Exception as e:
        ctx.record_failure(ctx.current_step, str(e))
        finalizer.finalize(ctx)  # emit-only: failed traces are never persisted
        TraceContext.deactivate(ctx_token)
        raise HTTPException(
            status_code=500,
            detail={"detail": str(e), "request_id": ctx.request_id},
        )

    async def event_stream():
        # Request_ID reaches the client before any token (Req 1.3).
        yield AgentEvent.meta(ctx.request_id).to_ndjson()
        try:
            if first is not None and first.type != "done":
                if first.type == "token":
                    ctx.mark_first_token()
                yield first.to_ndjson()
            async for event in stream:
                if event.type == "done":
                    # Replaced by the request_id-carrying done below.
                    continue
                if event.type == "token":
                    ctx.mark_first_token()
                yield event.to_ndjson()
            yield AgentEvent.done(ctx.request_id).to_ndjson()  # Req 1.3
        except Exception as e:
            # Surface mid-stream failures as an error event the UI can show,
            # attributed to the step that was running (Req 1.5, 2.6).
            ctx.record_failure(ctx.current_step, str(e))
            yield AgentEvent.error(str(e), ctx.request_id).to_ndjson()
        finally:
            # After the last token, before the generator returns (Req 3.2);
            # emit always, persist success-only.
            finalizer.finalize(ctx)
            try:
                TraceContext.deactivate(ctx_token)
            except ValueError:
                # Starlette may drain the generator in a child task whose
                # context is a copy; that copy dies with the task, so the
                # failed reset is harmless.
                pass

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
app.include_router(feedback_router)
