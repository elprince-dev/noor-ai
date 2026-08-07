"""Property 17: Item failures are isolated and attributed (design.md
Correctness Properties).

*For any* run in which a random subset of items fails at random steps
(retrieval, retrieval-recording, or generation), exactly those items are
recorded as failed with the failing step and an error description (with
generation skipped when retrieval recording failed), all remaining items
complete, and the report's succeeded/failed counts match.

**Validates: Requirements 6.4, 6.5**

Pure in-memory Hypothesis test — no AWS calls, no filesystem. The strategy
generates small Golden_Datasets where each item is scripted with one of four
modes:

- "ok"                      — retrieval and generation both succeed;
- "retrieval_raises"        — the retrieval client raises;
- "retrieval_unrecordable"  — retrieval returns output that cannot be
                              recorded faithfully (non-str Source_ID or
                              non-numeric score), which per Req 6.4 fails
                              the item at "retrieval" and skips generation;
- "generation_raises"       — the generation client raises, with the
                              retrieval results retained (Req 6.5).

The fakes record every call so the test can assert:

(a) each failed item's report entry has failed=True, the correct
    failing_step and a non-empty error description;
(b) generation is never called for items whose retrieval failed;
(c) items failing at generation retain their retrieved Source_IDs/scores;
(d) all non-failed items execute completely and are recorded faithfully;
(e) counts.succeeded / counts.failed are exact;
(f) failed items never reach the scorer's score_item — their report entry
    carries not-computed generation scores (computed is False).
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import GoldenDataset, GoldenItem
from evals.eval_config import EvalConfig
from evals.metrics.generation import (
    GenerationAggregates,
    ItemGenerationScores,
    RubricOutcome,
)
from evals.metrics.generation import aggregate as aggregate_generation
from evals.pipeline import RetrievalResult
from evals.runner import EvalRunner

# -- strategies ---------------------------------------------------------------

CATEGORIES = ("direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus")

MODES = ("ok", "retrieval_raises", "retrieval_unrecordable", "generation_raises")

# Modes whose failure is attributed to the retrieval step (Req 6.4, 6.5).
RETRIEVAL_FAILURE_MODES = ("retrieval_raises", "retrieval_unrecordable")

# Question/answer text spanning ASCII and Arabic script.
text_content = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),
        st.sampled_from('"\\\n\t؟🕌'),
    ),
    min_size=1,
    max_size=40,
)

retrieved_source_id = st.text(min_size=1, max_size=20)

# Recordable scores: round-trip through float() in the runner; exclude NaN
# (breaks equality) and infinities (not meaningful relevance scores).
scores = st.floats(allow_nan=False, allow_infinity=False, width=32)

# A well-formed, recordable retrieval entry: (Source_ID, score, chunk text).
good_entries = st.tuples(retrieved_source_id, scores, text_content)

# Unrecordable entries per the runner's recording contract: a non-string
# Source_ID or a non-numeric score (bool counts as non-numeric, Req 6.4).
bad_source_ids = st.sampled_from((None, 42, 3.14, ("t",)))
bad_scores = st.sampled_from((None, "high", True, [1.0]))
bad_entries = st.one_of(
    st.tuples(bad_source_ids, scores, text_content),
    st.tuples(retrieved_source_id, bad_scores, text_content),
    st.tuples(bad_source_ids, bad_scores, text_content),
)


def _to_result(entries: list[tuple]) -> RetrievalResult:
    return RetrievalResult(
        sources=[(sid, score) for sid, score, _ in entries],
        context="\n".join(f"[{sid}] {text}" for sid, _, text in entries),
        texts=tuple(text for _, _, text in entries),
    )


# A recordable retrieval output (zero results is legal and recordable).
recordable_retrievals = st.lists(good_entries, min_size=0, max_size=4).map(_to_result)


@st.composite
def unrecordable_retrievals(draw) -> RetrievalResult:
    """A retrieval output with at least one unrecordable entry, at a random
    position among otherwise-good entries."""
    good = draw(st.lists(good_entries, min_size=0, max_size=3))
    bad = draw(st.lists(bad_entries, min_size=1, max_size=2))
    entries = good + bad
    # Shuffle so the bad entry isn't always last.
    entries = draw(st.permutations(entries))
    return _to_result(list(entries))


@st.composite
def datasets_with_failure_scripts(draw):
    """A small GoldenDataset plus per-item scripted mode and pipeline outputs.

    Returns (dataset, mode_by_question, retrieval_by_question,
    answer_by_question). Questions embed each item's unique id so the fakes
    can key their scripts by question.
    """
    n = draw(st.integers(min_value=1, max_value=8))
    items: list[GoldenItem] = []
    mode_by_question: dict[str, str] = {}
    retrieval_by_question: dict[str, RetrievalResult] = {}
    answer_by_question: dict[str, str] = {}

    for i in range(n):
        item_id = f"item-{i:03d}"
        question = f"{draw(text_content)} #{item_id}"  # unique per item
        category = draw(st.sampled_from(CATEGORIES))
        expected = (
            ()
            if category == "out_of_corpus"
            else tuple(
                draw(
                    st.lists(
                        st.integers(1, 6236).map(lambda v: f"Sahih Muslim {v}"),
                        min_size=1,
                        max_size=2,
                        unique=True,
                    )
                )
            )
        )
        items.append(
            GoldenItem(
                id=item_id,
                question=question,
                language=draw(st.sampled_from(("ar", "en"))),
                category=category,
                expected_source_ids=expected,
                counterpart_id="peer" if category == "cross_lingual" else None,
            )
        )

        mode = draw(st.sampled_from(MODES))
        mode_by_question[question] = mode
        if mode == "retrieval_unrecordable":
            retrieval_by_question[question] = draw(unrecordable_retrievals())
        elif mode != "retrieval_raises":
            retrieval_by_question[question] = draw(recordable_retrievals)
        if mode in ("ok", "generation_raises"):
            answer_by_question[question] = draw(text_content)

    dataset = GoldenDataset(items=tuple(items), version="1.0.0+deadbeef1234")
    return dataset, mode_by_question, retrieval_by_question, answer_by_question


eval_configs = st.builds(
    EvalConfig,
    model_id=st.just("us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    retrieval_top_k=st.integers(min_value=1, max_value=10),
    prompt_version=st.sampled_from(("v1", "v2")),
    judge_model_id=st.just("amazon.nova-pro-v1:0"),
)


# -- in-memory fakes (no AWS) --------------------------------------------------


class FailableRetrievalClient:
    """Returns the scripted RetrievalResult, or raises for retrieval_raises
    items; records every call."""

    def __init__(
        self, script: dict[str, RetrievalResult], modes: dict[str, str]
    ) -> None:
        self._script = script
        self._modes = modes
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, question: str, top_k: int) -> RetrievalResult:
        self.calls.append((question, top_k))
        assert question in self._modes, f"unexpected retrieval question {question!r}"
        if self._modes[question] == "retrieval_raises":
            raise RuntimeError(f"scripted retrieval outage for {question!r}")
        return self._script[question]


class FailableGenerationClient:
    """Returns the scripted answer, or raises for generation_raises items;
    records every call so the test can prove generation is skipped for
    retrieval-failed items (Req 6.4)."""

    def __init__(self, script: dict[str, str], modes: dict[str, str]) -> None:
        self._script = script
        self._modes = modes
        self.calls: list[tuple[str, str, str]] = []  # (question, context, version)

    def generate(self, question: str, context: str, prompt_version: str) -> str:
        self.calls.append((question, context, prompt_version))
        assert question in self._modes, f"unexpected generation question {question!r}"
        if self._modes[question] == "generation_raises":
            raise RuntimeError(f"scripted generation outage for {question!r}")
        return self._script[question]


class RecordingScorer:
    """GenerationScorerLike fake: records score_item calls so the test can
    prove failed items never reach the scorer (Req 8.9 via Property 17f)."""

    def __init__(self) -> None:
        self.score_calls: list[str] = []  # item ids

    def score_item(self, item, answer, retrieved) -> ItemGenerationScores:
        self.score_calls.append(item.id)
        return ItemGenerationScores(
            item_id=item.id,
            category=item.category,
            language=item.language,
            computed=True,
            outcomes=(
                RubricOutcome(rubric="faithfulness", outcome="pass", rationale="ok"),
            ),
        )

    def aggregate(self, item_scores) -> GenerationAggregates:
        return aggregate_generation(item_scores)


class RecordingReports:
    """ReportRepositoryLike fake: records every persisted payload."""

    def __init__(self) -> None:
        self.persisted: list[dict] = []

    def persist(self, report: dict) -> None:
        self.persisted.append(report)


# -- the property --------------------------------------------------------------


class TestProperty17ItemFailureIsolation:
    @settings(max_examples=100)
    @given(data=datasets_with_failure_scripts(), config=eval_configs)
    def test_failures_are_isolated_and_attributed(self, data, config):
        dataset, modes, retrieval_script, answer_script = data
        retrieval = FailableRetrievalClient(retrieval_script, modes)
        generator = FailableGenerationClient(answer_script, modes)
        scorer = RecordingScorer()
        reports = RecordingReports()

        report = EvalRunner(retrieval, generator, scorer, reports).run(config, dataset)

        # The run continued past every failure: every item was attempted
        # through retrieval exactly once, in dataset order (Req 6.5).
        assert [q for q, _ in retrieval.calls] == [i.question for i in dataset.items]
        assert len(report["per_item"]) == len(dataset.items)

        # (b) Generation is never called for items whose retrieval failed
        # (raised or unrecordable output); it is called exactly once for
        # every other item, in dataset order (Req 6.4).
        assert [q for q, _, _ in generator.calls] == [
            item.question
            for item in dataset.items
            if modes[item.question] not in RETRIEVAL_FAILURE_MODES
        ]

        # (f) Failed items never reach the scorer's score_item; only fully
        # successful items are scored.
        ok_ids = [i.id for i in dataset.items if modes[i.question] == "ok"]
        assert scorer.score_calls == ok_ids

        for item, entry in zip(dataset.items, report["per_item"]):
            mode = modes[item.question]
            assert entry["item_id"] == item.id

            if mode == "ok":
                # (d) Non-failed items execute completely and are recorded
                # faithfully: exact Source_IDs with scores in rank order,
                # the generated answer, and no failure attribution.
                scripted = retrieval_script[item.question]
                assert entry["failed"] is False
                assert entry["failing_step"] is None
                assert entry["error"] is None
                assert entry["retrieved"] == [
                    [sid, float(score)] for sid, score in scripted.sources
                ]
                assert entry["answer"] == answer_script[item.question]
                assert entry["generation_scores"]["computed"] is True
                continue

            # (a) Every failed item is attributed: failed=True, the correct
            # failing step, and a non-empty error description (Req 6.5).
            assert entry["failed"] is True
            expected_step = (
                "retrieval" if mode in RETRIEVAL_FAILURE_MODES else "generation"
            )
            assert entry["failing_step"] == expected_step
            assert isinstance(entry["error"], str) and entry["error"]
            assert entry["answer"] is None

            # (f) Failed items carry not-computed generation scores instead
            # of judge verdicts.
            assert entry["generation_scores"]["computed"] is False
            assert entry["generation_scores"]["outcomes"] == ()

            if mode == "generation_raises":
                # (c) Generation failures retain the retrieved
                # Source_IDs/scores exactly as recorded (Req 6.5).
                scripted = retrieval_script[item.question]
                assert entry["retrieved"] == [
                    [sid, float(score)] for sid, score in scripted.sources
                ]
            else:
                # Retrieval failures retain nothing.
                assert entry["retrieved"] == []

        # (e) The report's succeeded/failed counts are exact (Req 6.5, 6.7).
        failed_count = sum(1 for i in dataset.items if modes[i.question] != "ok")
        assert report["counts"] == {
            "succeeded": len(dataset.items) - failed_count,
            "failed": failed_count,
        }

        # The report was persisted once despite any failures.
        assert reports.persisted == [report]
