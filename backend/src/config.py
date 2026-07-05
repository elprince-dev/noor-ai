import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Application configuration from environment variables."""

    chat_table: str = os.environ.get("CHAT_TABLE", "noor-ai-chat-history")
    bedrock_model_id: str = os.environ.get(
        "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
    )
    bedrock_region: str = os.environ.get("BEDROCK_REGION", "us-east-1")
    session_ttl_hours: int = int(os.environ.get("SESSION_TTL_HOURS", "72"))
    max_history_messages: int = int(os.environ.get("MAX_HISTORY_MESSAGES", "20"))


config = Config()
