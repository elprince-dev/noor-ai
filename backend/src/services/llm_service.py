from langchain_aws import ChatBedrock
from langchain_core.language_models import BaseChatModel

from src.config import config


class LLMService:
    """Manages Bedrock LLM instances.

    Uses a singleton pattern so the model is reused across Lambda invocations
    (Lambda container reuse).
    """

    _instance: BaseChatModel | None = None

    @classmethod
    def get_model(cls) -> BaseChatModel:
        """Get or create the LLM instance."""
        if cls._instance is None:
            cls._instance = ChatBedrock(
                model_id=config.bedrock_model_id,
                region_name=config.bedrock_region,
                model_kwargs={"temperature": 0, "max_tokens": 2048},
            )
        return cls._instance
