import os
from dataclasses import dataclass
from pathlib import Path

# Load .env file if it exists (local dev only — Lambda sets env vars directly)
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv

    load_dotenv(_env_file)


@dataclass(frozen=True)
class Config:
    """Application configuration from environment variables."""

    chat_table: str = os.environ.get("CHAT_TABLE", "noor-ai-chat-history")
    bedrock_model_id: str = os.environ.get(
        "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    bedrock_region: str = os.environ.get("BEDROCK_REGION", "us-east-1")
    session_ttl_hours: int = int(os.environ.get("SESSION_TTL_HOURS", "72"))
    max_history_messages: int = int(os.environ.get("MAX_HISTORY_MESSAGES", "20"))


config = Config()
