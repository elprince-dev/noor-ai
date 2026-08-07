"""Immutable trace data types (schema version 1).

These are pure value objects — no I/O, no behavior beyond serialization.
The `Trace` shape mirrors the persisted DynamoDB item and the CloudWatch
log line (which adds `log_type: "trace"` at emission time).
"""
from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Per-1K-token pricing for one model, in USD."""

    input_per_1k: float
    output_per_1k: float


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Estimated request cost in USD, or an explicit not-computed marker.

    Never zero or substituted when token counts or pricing are missing
    (Req 2.8, 2.9) — `computed=False` with a reason instead.
    """

    computed: bool
    usd: float | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        if self.computed:
            return {"computed": True, "usd": self.usd}
        return {"computed": False, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """One retrieved chunk: its Source_ID (corpus citation) and score."""

    source_id: str
    score: float

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "score": self.score}


@dataclass(frozen=True, slots=True)
class RetrievalRecord:
    """One retrieval tool call: ordered results and latency (Req 2.2)."""

    tool: str
    latency_ms: int
    results: tuple[RetrievalResult, ...]

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "latency_ms": self.latency_ms,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass(frozen=True, slots=True)
class TraceFailure:
    """The failing pipeline step and error message (Req 2.6)."""

    step: str
    error: str

    def to_dict(self) -> dict:
        return {"step": self.step, "error": self.error}


@dataclass(frozen=True, slots=True)
class Trace:
    """One structured record of a single chat request (schema version 1).

    `None` fields mean "not captured": token counts unavailable (Req 2.8),
    TTFT never marked (Req 2.10), or the pipeline failed before the field
    was recorded. `TraceContext.build_trace()` is the only producer.
    """

    request_id: str
    session_id: str
    received_at: str  # UTC ISO-8601
    query: str
    model_id: str
    retrieval: tuple[RetrievalRecord, ...]
    final_prompt: str | None
    response: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost: CostEstimate
    ttft_ms: int | None
    total_latency_ms: int
    failure: TraceFailure | None = None
    truncated: bool = False
    schema_version: int = field(default=SCHEMA_VERSION)

    def to_dict(self) -> dict:
        """Serialize to the schema-version-1 JSON shape."""
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "received_at": self.received_at,
            "query": self.query,
            "model_id": self.model_id,
            "retrieval": [r.to_dict() for r in self.retrieval],
            "final_prompt": self.final_prompt,
            "response": self.response,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": self.cost.to_dict(),
            "ttft_ms": self.ttft_ms,
            "total_latency_ms": self.total_latency_ms,
            "failure": self.failure.to_dict() if self.failure else None,
            "truncated": self.truncated,
        }
