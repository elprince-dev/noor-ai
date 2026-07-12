from langchain_aws import ChatBedrockConverse
from langchain_core.language_models import BaseChatModel

from src.config import config


class LLMService:
    """Manages Bedrock LLM instances.

    Uses ChatBedrockConverse (Converse API) which provides:
    - Better tool calling support (for future agent phase)
    - Standardized interface across all Bedrock models
    - Cleaner parameter handling

    Singleton pattern ensures the model is reused across Lambda invocations
    (Lambda container reuse).
    """

    _instance: BaseChatModel | None = None

    @classmethod
    def get_model(cls) -> BaseChatModel:
        """Get or create the LLM instance."""
        if cls._instance is None:
            cls._instance = ChatBedrockConverse(
                model=config.bedrock_model_id,
                region_name=config.bedrock_region,
                temperature=0,
                max_tokens=2048,
            )
        return cls._instance

    @staticmethod
    def extract_text(content) -> str:
        """Extract plain text from a message (chunk) content payload.

        ChatBedrockConverse (Converse API) emits content as a list of blocks,
        e.g. [{"type": "text", "text": "..."}], while other providers emit a
        plain string. Handles both; non-text blocks (tool use, etc.) are
        ignored. Kept here so model-format knowledge stays in the LLM layer.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return ""
