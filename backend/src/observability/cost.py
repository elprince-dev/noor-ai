"""Token counts + pricing → `CostEstimate` (pure) — Req 2.5, 2.8, 2.9.

`CostEstimator` turns recorded token counts and the per-model pricing table
into an estimated USD cost. The pricing table is injected via the
constructor (production wiring passes `config.MODEL_PRICING`), so tests can
exercise arbitrary tables without touching global config.

Lookup is by substring match of the pricing key against the configured
model ID, because cross-region inference profile prefixes vary (e.g. the
key "anthropic.claude-haiku-4-5" matches the model ID
"us.anthropic.claude-haiku-4-5-20251001-v1:0").
"""
from src.observability.models import CostEstimate, ModelPricing


class CostEstimator:
    """Pure cost estimation from token counts and injected pricing."""

    def __init__(self, pricing: dict[str, ModelPricing]) -> None:
        self._pricing = pricing

    def estimate(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
        model_id: str,
    ) -> CostEstimate:
        """Return the estimated USD cost, or an explicit not-computed marker.

        Not-computed (never zero or substituted) when either token count is
        `None` (Req 2.8) or no pricing entry matches the model ID (Req 2.9).
        Otherwise (Req 2.5):
        cost = (input/1000) * input_per_1k + (output/1000) * output_per_1k
        """
        if input_tokens is None or output_tokens is None:
            return CostEstimate(computed=False, reason="token counts unavailable")

        pricing = self._lookup(model_id)
        if pricing is None:
            return CostEstimate(
                computed=False,
                reason=f"no pricing configured for model {model_id!r}",
            )

        usd = (
            (input_tokens / 1000) * pricing.input_per_1k
            + (output_tokens / 1000) * pricing.output_per_1k
        )
        return CostEstimate(computed=True, usd=usd)

    def _lookup(self, model_id: str) -> ModelPricing | None:
        """First pricing entry whose key is a substring of `model_id`."""
        for key, pricing in self._pricing.items():
            if key in model_id:
                return pricing
        return None
