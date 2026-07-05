from pydantic import BaseModel


class AskResponse(BaseModel):
    """Response body for the /ask endpoint."""

    answer: str
    session_id: str


class SessionResponse(BaseModel):
    """Response body for the /sessions endpoint."""

    session_id: str


class HealthResponse(BaseModel):
    """Response body for the /health endpoint."""

    status: str
    model: str
