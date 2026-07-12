import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentEvent:
    """A single structured event in the agentic answer stream.

    Serialized as one NDJSON line per event. Owning event shape here keeps the
    wire contract in one place, independent of how the agent produces them
    (ConversationChain) or how they're transported (app.py).
    """

    type: str  # "token" | "tool_start" | "tool_end" | "done" | "error"
    data: dict = field(default_factory=dict)

    def to_ndjson(self) -> str:
        return json.dumps({"type": self.type, **self.data}, ensure_ascii=False) + "\n"

    # ── Factories ────────────────────────────────────────────────
    @staticmethod
    def token(text: str) -> "AgentEvent":
        return AgentEvent("token", {"text": text})

    @staticmethod
    def tool_start(run_id: str, tool: str, query: str) -> "AgentEvent":
        return AgentEvent("tool_start", {"id": run_id, "tool": tool, "query": query})

    @staticmethod
    def tool_end(run_id: str, tool: str, ms: int, count: int) -> "AgentEvent":
        return AgentEvent(
            "tool_end", {"id": run_id, "tool": tool, "ms": ms, "count": count}
        )

    @staticmethod
    def done() -> "AgentEvent":
        return AgentEvent("done")

    @staticmethod
    def error(detail: str) -> "AgentEvent":
        return AgentEvent("error", {"detail": detail})