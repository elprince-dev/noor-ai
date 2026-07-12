from langchain.agents import create_agent

from src.services.llm_service import LLMService
from src.tools.rag_tools import RagToolset
from src.prompts.islamic_qa import AGENT_SYSTEM_PROMPT


class AgentFactory:
    """Constructs the tool-calling agent (LangChain 1.0 `create_agent`).

    Single responsibility: wire model + retrieval tools + system prompt into a
    compiled agent. Kept separate from ConversationChain so *construction* is
    decoupled from *execution* (loading history, streaming, persistence).

    Singleton: the compiled agent is reused across Lambda invocations.
    """

    _agent = None

    @classmethod
    def get_agent(cls):
        if cls._agent is None:
            cls._agent = create_agent(
                model=LLMService.get_model(),
                tools=RagToolset().as_tools(),
                system_prompt=AGENT_SYSTEM_PROMPT,
            )
        return cls._agent