from pydantic import BaseModel, Field
from typing import Literal


class AskRequest(BaseModel):
    """Request body for the /ask endpoint."""

    question: str = Field(max_length=1000, description="The user's question")
    session_id: str = Field(description="Session ID for conversation continuity")
    school: Literal["hanafi", "maliki", "shafii", "hanbali", "general"] = Field(
        default="general",
        description="Preferred school of thought",
    )
