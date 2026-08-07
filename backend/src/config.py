import os
from dataclasses import dataclass
from pathlib import Path

from src.observability.models import ModelPricing

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
    knowledge_base_id: str = os.environ.get("KNOWLEDGE_BASE_ID", "")
    retrieval_top_k: int = int(os.environ.get("RETRIEVAL_TOP_K", "5"))


config = Config()

# Per-model pricing in USD per 1K tokens, keyed by model-ID substring.
# Lookup is by substring match against the configured model ID, so one
# entry covers cross-region inference profile variants (e.g. the key
# "anthropic.claude-haiku-4-5" matches "us.anthropic.claude-haiku-4-5-...").
MODEL_PRICING: dict[str, ModelPricing] = {
    "anthropic.claude-haiku-4-5": ModelPricing(input_per_1k=0.001, output_per_1k=0.005),
}
