"""EvalRunner: per-item execution loop (Req 6.1, 6.3, 6.4, 6.5, 6.7).

`EvalRunner.run(config, dataset)` executes every Golden_Item through one
retrieval step and one generation step, each item fully independent — the
runner holds no per-item mutable state and the injected clients are called
once per item with only that item's question (Req 6.1). Item failures are
isolated: a failed item records its failing step and error description, and
the run continues with the remaining items (Req 6.4, 6.5).

Collaborators arrive via constructor injection so property tests can use
in-memory fakes (design §runner.py):

- `retrieval: RetrievalClient` / `generator: GenerationClient` — the
  protocols from `pipeline.py`.
- `scorer` — the `GenerationScorer` contract from `metrics/generation.py`,
  typed here as `GenerationScorerLike`:
    - `score_item(item, answer, retrieved) -> ItemGenerationScores` is
      called only for items that completed both steps; failed items are
      marked not-computed via `metrics.generation.not_computed(item)` and
      never reach the scorer or the judge (Req 8.9).
    - `aggregate(scores) -> GenerationAggregates` folds the per-item scores
      into generation aggregates.
- `reports` — the ReportRepository contract (implemented in `report.py`,
  task 11.1), typed here as `ReportRepositoryLike`:
    - `persist(report: dict[str, Any]) -> None` receives the assembled,
      JSON-serializable report payload. Assigning the `run_id` (and
      regenerating it on collision) is the repository's concern, since only
      it can detect collisions among persisted reports (design §report.py).

The report payload assembled by `run()` carries every design-mandated field
except `run_id`: `config`, `dataset_version`, `completed_at`, `aggregates`
(retrieval + generation), `per_item` (each item's result joined with its
generation scores), and `counts {succeeded, failed}` (Req 6.7).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from evals.dataset import GoldenDataset, GoldenItem
from evals.eval_config import EvalConfig
from evals.judge import RetrievedChunk
from evals.metrics.generation import (
    GenerationAggregates,
    ItemGenerationScores,
    not_computed,
)
from evals.metrics.retrieval import RetrievalItemInput
from evals.metrics.retrieval import aggregate as aggregate_retrieval
from evals.pipeline import GenerationClient, RetrievalClient, RetrievalResult


@dataclass(frozen=True, slots=True)
class ItemResult:
    """One per-item result: ID, retrieved Source_IDs with scores, and answer
    recorded together (Req 6.3), or a failure record naming the failing step
    and error description (Req 6.5).

    On generation failure the retrieval results are retained (`retrieved`
    stays populated, `answer` is None). On retrieval failure both are empty.
    `chunk_texts` carries the raw chunk texts aligned with `retrieved` so
    the judge can see each chunk labeled with its Source_ID (Req 8.1, 8.2);
    it is execution plumbing, not part of the reported per-item record.
    """

    item_id: str
    retrieved: tuple[tuple[str, float], ...]  # (Source_ID, score), rank order
    answer: str | None
    failed: bool = False
    failing_step: str | None = None  # "retrieval" | "generation" when failed
    error: str | None = None
    chunk_texts: tuple[str, ...] = ()  # aligned with `retrieved`

    def to_dict(self) -> dict[str, Any]:
        """The reported per-item record (Req 6.3, 6.5, 9.2)."""
        return {
            "item_id": self.item_id,
            "retrieved": [[source_id, score] for source_id, score in self.retrieved],
            "answer": self.answer,
            "failed": self.failed,
            "failing_step": self.failing_step,
            "error": self.error,
        }


class GenerationScorerLike(Protocol):
    """The `GenerationScorer` surface the runner depends on (metrics/generation.py)."""

    def score_item(
        self,
        item: GoldenItem,
        answer: str,
        retrieved: Sequence[RetrievedChunk],
    ) -> ItemGenerationScores: ...

    def aggregate(
        self, scores: Sequence[ItemGenerationScores]
    ) -> GenerationAggregates: ...


class ReportRepositoryLike(Protocol):
    """Minimal contract for the ReportRepository (task 11.1, design §report.py).

    `persist` receives the assembled JSON-serializable report payload (no
    `run_id` — the repository generates it, regenerating on collision) and
    writes it append-only under `results/{run_id}/report.json`.
    """

    def persist(self, report: dict[str, Any]) -> None: ...


class EvalRunner:
    """Executes a Golden_Dataset through retrieval + generation and reports.

    Holds only the injected collaborators — no per-run or per-item mutable
    state — so every Golden_Item executes independently (Req 6.1).
    """

    def __init__(
        self,
        retrieval: RetrievalClient,
        generator: GenerationClient,
        scorer: GenerationScorerLike,
        reports: ReportRepositoryLike,
    ) -> None:
        self._retrieval = retrieval
        self._generator = generator
        self._scorer = scorer
        self._reports = reports

    def run(self, config: EvalConfig, dataset: GoldenDataset) -> dict[str, Any]:
        """Execute every item, compute metrics, build and persist the report.

        Each item runs independently through `_execute_item`; failures are
        recorded and never stop the run (Req 6.1, 6.5). Retrieval aggregates
        come from `metrics.retrieval.aggregate`; generation scores from the
        injected scorer (failed items marked not-computed, never scored,
        Req 8.9). The assembled report is persisted via the injected
        repository and returned (Req 6.7).
        """
        results = [self._execute_item(item, config) for item in dataset.items]

        retrieval_aggregates = aggregate_retrieval(
            [
                RetrievalItemInput(
                    item_id=item.id,
                    category=item.category,
                    language=item.language,
                    expected_source_ids=item.expected_source_ids,
                    retrieved_source_ids=tuple(sid for sid, _ in result.retrieved),
                    failed=result.failed,
                )
                for item, result in zip(dataset.items, results)
            ],
            k=config.retrieval_top_k,
        )

        item_scores = [
            self._score_item(item, result)
            for item, result in zip(dataset.items, results)
        ]
        generation_aggregates = self._scorer.aggregate(item_scores)

        report: dict[str, Any] = {
            "config": asdict(config),
            "dataset_version": dataset.version,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "aggregates": {
                "retrieval": asdict(retrieval_aggregates),
                "generation": asdict(generation_aggregates),
            },
            "per_item": [
                {**result.to_dict(), "generation_scores": asdict(scores)}
                for result, scores in zip(results, item_scores)
            ],
            "counts": {
                "succeeded": sum(1 for r in results if not r.failed),
                "failed": sum(1 for r in results if r.failed),
            },
        }
        self._reports.persist(report)
        return report

    def _score_item(self, item: GoldenItem, result: ItemResult) -> ItemGenerationScores:
        """Generation scores for one item; failed items never reach the scorer (Req 8.9)."""
        if result.failed or result.answer is None:
            return not_computed(item)
        chunks = [
            RetrievedChunk(source_id=source_id, text=text)
            for (source_id, _), text in zip(result.retrieved, result.chunk_texts)
        ]
        return self._scorer.score_item(item, result.answer, chunks)

    def _execute_item(self, item: GoldenItem, config: EvalConfig) -> ItemResult:
        """Run one Golden_Item through retrieval then generation.

        Failure semantics (Req 6.4, 6.5):
        - retrieval raises            => failed(step="retrieval"), nothing retained
        - recording retrieval fails   => failed(step="retrieval"), generation skipped
        - generation raises           => failed(step="generation"), retrieval retained
        """
        # Step 1 — retrieval (any exception => failed at "retrieval").
        try:
            retrieval_result = self._retrieval.retrieve(
                item.question, config.retrieval_top_k
            )
        except Exception as exc:  # noqa: BLE001 — isolate per-item failures (Req 6.5)
            return ItemResult(
                item_id=item.id,
                retrieved=(),
                answer=None,
                failed=True,
                failing_step="retrieval",
                error=f"retrieval failed: {exc}",
            )

        # Step 1b — record the retrieved Source_IDs with scores; if recording
        # fails, skip generation and mark the item failed (Req 6.4).
        try:
            retrieved, chunk_texts = self._record_sources(retrieval_result)
        except Exception as exc:  # noqa: BLE001
            return ItemResult(
                item_id=item.id,
                retrieved=(),
                answer=None,
                failed=True,
                failing_step="retrieval",
                error=f"recording retrieved Source_IDs failed: {exc}",
            )

        # Step 2 — generation, one-shot with this item's context only; no
        # memory or session, so items stay independent (Req 6.1). Any
        # exception => failed at "generation" with retrieval retained (Req 6.5).
        try:
            answer = self._generator.generate(
                item.question, retrieval_result.context, config.prompt_version
            )
        except Exception as exc:  # noqa: BLE001
            return ItemResult(
                item_id=item.id,
                retrieved=retrieved,
                answer=None,
                failed=True,
                failing_step="generation",
                error=f"generation failed: {exc}",
                chunk_texts=chunk_texts,
            )

        return ItemResult(
            item_id=item.id,
            retrieved=retrieved,
            answer=answer,
            failed=False,
            chunk_texts=chunk_texts,
        )

    @staticmethod
    def _record_sources(
        retrieval_result: RetrievalResult,
    ) -> tuple[tuple[tuple[str, float], ...], tuple[str, ...]]:
        """Normalize retrieval output into recorded (Source_ID, score) pairs
        plus the aligned chunk texts.

        Raises when the output cannot be recorded faithfully — a non-string
        Source_ID or non-numeric score — which per Req 6.4 fails the item
        and skips generation. Missing chunk texts (e.g. a fake client that
        omits them) are tolerated as empty strings; texts are judge plumbing,
        not part of the recorded result.
        """
        recorded: list[tuple[str, float]] = []
        for entry in retrieval_result.sources:
            source_id, score = entry
            if (
                not isinstance(source_id, str)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
            ):
                raise TypeError(
                    f"unrecordable retrieval entry {entry!r}: "
                    "expected (str Source_ID, numeric score)"
                )
            recorded.append((source_id, float(score)))
        texts = tuple(retrieval_result.texts[: len(recorded)]) + ("",) * max(
            0, len(recorded) - len(retrieval_result.texts)
        )
        return tuple(recorded), texts
