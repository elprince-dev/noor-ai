"""Generation scoring policy: rubric selection, retry, pass-rate aggregation.

`GenerationScorer` owns everything about *how* judge verdicts are obtained
and combined (Req 8.4, 8.6, 8.7, 8.9); the judge itself is injected via the
`Judge` protocol so property tests run against scripted fakes — never AWS.

Policy summary:

- Rubric selection (Req 8.4): out_of_corpus items get the single abstention
  rubric; every other category gets faithfulness + citation accuracy +
  answer relevancy.
- Retry discipline (Req 8.6): each (item, rubric) scoring call that raises
  (transport failure or `VerdictParseError`) is retried exactly once; a
  second failure records the outcome `"error"` — distinct from pass and
  fail — and scoring continues with the remaining rubrics and items.
- Failed items (Req 8.9): the runner must never call `score_item` for items
  recorded as failed; it marks them via `not_computed(item)` instead, and
  `aggregate` excludes them from every pass rate and error count.
- Aggregation (Req 8.7): per-metric pass rate = pass / (pass + fail) with
  error outcomes excluded from both numerator and denominator (`None` when
  the denominator is zero), plus a per-metric error count — overall, by
  category, and by language.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from evals.dataset import GoldenItem
from evals.judge import (
    ABSTENTION,
    ANSWER_RELEVANCY,
    CITATION_ACCURACY,
    FAITHFULNESS,
    Judge,
    RetrievedChunk,
    Rubric,
)

# Per-rubric outcome values. PASS/FAIL come from the judge's Verdict; ERROR
# is recorded by the scorer after the single retry also fails (Req 8.6).
PASS = "pass"
FAIL = "fail"
ERROR = "error"


@dataclass(frozen=True, slots=True)
class RubricOutcome:
    """The recorded result of scoring one (item, rubric) pair.

    `outcome` is "pass" or "fail" (judge verdict) or "error" (both scoring
    attempts failed); for errors, `rationale` carries the final exception
    message instead of a judge rationale.
    """

    rubric: str
    outcome: str  # PASS | FAIL | ERROR
    rationale: str


@dataclass(frozen=True, slots=True)
class ItemGenerationScores:
    """Per-item Generation_Metrics; `computed=False` marks not-computed (Req 8.9).

    Carries category and language so `aggregate` can group without needing
    the Golden_Items again. Not-computed items (failed during execution)
    have an empty `outcomes` tuple.
    """

    item_id: str
    category: str
    language: str
    computed: bool
    outcomes: tuple[RubricOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricPassRate:
    """Pass rate + error count for one metric over one group (Req 8.7).

    `pass_rate` is pass / (pass + fail); `None` when there are zero pass or
    fail verdicts for the metric in the group (errors never substitute).
    """

    pass_rate: float | None
    pass_count: int
    fail_count: int
    error_count: int


@dataclass(frozen=True, slots=True)
class GenerationAggregates:
    """Per-item scores plus overall / by-category / by-language pass rates.

    Each mapping is keyed by rubric name; a rubric appears in a group only
    when at least one computed item in that group was scored against it
    (out_of_corpus items contribute only the abstention rubric, Req 8.4).
    """

    per_item: tuple[ItemGenerationScores, ...]
    overall: dict[str, MetricPassRate]
    by_category: dict[str, dict[str, MetricPassRate]]
    by_language: dict[str, dict[str, MetricPassRate]]


def rubrics_for(item: GoldenItem) -> tuple[Rubric, ...]:
    """The rubric set for one Golden_Item per its category (Req 8.4)."""
    if item.category == "out_of_corpus":
        return (ABSTENTION,)
    return (FAITHFULNESS, CITATION_ACCURACY, ANSWER_RELEVANCY)


def not_computed(item: GoldenItem) -> ItemGenerationScores:
    """Not-computed Generation_Metrics for an item that failed execution (Req 8.9).

    The runner uses this instead of `score_item` for failed items, so the
    judge is never invoked for them; `aggregate` excludes these from every
    pass rate and error count.
    """
    return ItemGenerationScores(
        item_id=item.id,
        category=item.category,
        language=item.language,
        computed=False,
    )


class GenerationScorer:
    """Scores generated answers via an injected `Judge` (design §generation.py)."""

    def __init__(self, judge: Judge) -> None:
        self._judge = judge

    def score_item(
        self,
        item: GoldenItem,
        answer: str,
        retrieved: Sequence[RetrievedChunk],
    ) -> ItemGenerationScores:
        """Score one successfully executed item against its rubric set.

        Must only be called for items that completed retrieval and
        generation; failed items go through `not_computed` (Req 8.9).
        Each rubric is scored with at most two judge calls (one retry,
        Req 8.6); an error on one rubric never stops the remaining rubrics.
        """
        outcomes = tuple(
            self._score_with_retry(rubric, item, answer, retrieved)
            for rubric in rubrics_for(item)
        )
        return ItemGenerationScores(
            item_id=item.id,
            category=item.category,
            language=item.language,
            computed=True,
            outcomes=outcomes,
        )

    def _score_with_retry(
        self,
        rubric: Rubric,
        item: GoldenItem,
        answer: str,
        retrieved: Sequence[RetrievedChunk],
    ) -> RubricOutcome:
        """One scoring call, retried exactly once on any failure (Req 8.6).

        Both a raised exception (transport failure, `VerdictParseError`) and
        its retry counterpart are absorbed; the second failure yields the
        `"error"` outcome carrying the final exception message.
        """
        last_error: Exception | None = None
        for _ in range(2):  # initial attempt + exactly one retry
            try:
                verdict = self._judge.score(rubric, item, answer, retrieved)
            except Exception as exc:  # noqa: BLE001 — any failure triggers the retry
                last_error = exc
                continue
            return RubricOutcome(
                rubric=rubric.name,
                outcome=verdict.verdict,
                rationale=verdict.rationale,
            )
        return RubricOutcome(
            rubric=rubric.name,
            outcome=ERROR,
            rationale=f"{type(last_error).__name__}: {last_error}",
        )

    def aggregate(self, scores: Sequence[ItemGenerationScores]) -> GenerationAggregates:
        """Delegates to the module-level pure `aggregate` (Req 8.7)."""
        return aggregate(scores)


def aggregate(scores: Sequence[ItemGenerationScores]) -> GenerationAggregates:
    """Per-metric pass rates and error counts over the computed items (Req 8.7, 8.9).

    Pass rate = pass / (pass + fail) with errors excluded from both
    numerator and denominator (`None` when that denominator is zero), plus
    the error count per metric — overall, by category, and by language.
    Not-computed items (failed during execution) are excluded entirely.
    """
    computed = [s for s in scores if s.computed]

    by_category: dict[str, dict[str, MetricPassRate]] = {}
    by_language: dict[str, dict[str, MetricPassRate]] = {}
    for category in sorted({s.category for s in computed}):
        by_category[category] = _pass_rates(
            [s for s in computed if s.category == category]
        )
    for language in sorted({s.language for s in computed}):
        by_language[language] = _pass_rates(
            [s for s in computed if s.language == language]
        )

    return GenerationAggregates(
        per_item=tuple(scores),
        overall=_pass_rates(computed),
        by_category=by_category,
        by_language=by_language,
    )


def _pass_rates(group: list[ItemGenerationScores]) -> dict[str, MetricPassRate]:
    """Pass rate + error count per rubric name over one group of computed items."""
    counts: dict[str, dict[str, int]] = {}
    for item_scores in group:
        for outcome in item_scores.outcomes:
            per_rubric = counts.setdefault(
                outcome.rubric, {PASS: 0, FAIL: 0, ERROR: 0}
            )
            per_rubric[outcome.outcome] += 1

    rates: dict[str, MetricPassRate] = {}
    for rubric_name in sorted(counts):
        per_rubric = counts[rubric_name]
        denominator = per_rubric[PASS] + per_rubric[FAIL]
        rates[rubric_name] = MetricPassRate(
            pass_rate=per_rubric[PASS] / denominator if denominator else None,
            pass_count=per_rubric[PASS],
            fail_count=per_rubric[FAIL],
            error_count=per_rubric[ERROR],
        )
    return rates
