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
