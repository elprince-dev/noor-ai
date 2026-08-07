"""Property 24: Failed items never reach the judge (design.md Correctness
Properties).

*For any* run with a random subset of failed items, the judge is invoked for
no failed item, generation metrics for failed items are marked not-computed,
and failed items are excluded from aggregate Generation_Metrics.

**Validates: Requirements 8.9**

Pure in-memory Hypothesis tests — no AWS calls, no filesystem. The property
is checked on both sides of the scorer boundary:

(a) Through the runner: a scripted mix of failing and succeeding items runs
    through `EvalRunner` with a *real* `GenerationScorer` over a recording
    `Judge` fake. The judge must be invoked exactly for the items that
    completed both retrieval and generation — zero invocations for any
    failed item — and every failed item's report entry must carry
    not-computed generation scores.

(b) Through `aggregate` directly: for any mix of computed and not-computed
    `ItemGenerationScores`, every pass/fail/error count in the aggregates
    (overall, by category, by language) derives only from the computed
    items — the not-computed items contribute nothing to any group, and a
    group populated only by not-computed items does not appear at all.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import GoldenDataset, GoldenItem
from evals.eval_config import EvalConfig
from evals.judge import Rubric, Verdict
from evals.metrics.generation import (
    ERROR,
    FAIL,
    PASS,
    GenerationScorer,
    ItemGenerationScores,
    MetricPassRate,
    RubricOutcome,
    aggregate,
    not_computed,
    rubrics_for,
)
from evals.pipeline import RetrievalResult
from evals.runner import EvalRunner

# -- shared strategies ---------------------------------------------------------

CATEGORIES = ("direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus")

MODES = ("ok", "retrieval_raises", "retrieval_unrecordable", "generation_raises")

# Modes whose failure is attributed to the retrieval step.
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
scores_st = st.floats(allow_nan=False, allow_infinity=False, width=32)

# A well-formed, recordable retrieval entry: (Source_ID, score, chunk text).
good_entries = st.tuples(retrieved_source_id, scores_st, text_content)

# Unrecordable entries: non-string Source_ID or non-numeric score.
bad_source_ids = st.sampled_from((None, 42, 3.14, ("t",)))
bad_scores = st.sampled_from((None, "high", True, [1.0]))
bad_entries = st.one_of(
    st.tuples(bad_source_ids, scores_st, text_content),
    st.tuples(retrieved_source_id, bad_scores, text_content),
    st.tuples(bad_source_ids, bad_scores, text_content),
)


def _to_result(entries: list[tuple]) -> RetrievalResult:
    return RetrievalResult(
        sources=[(sid, score) for sid, score, _ in entries],
        context="\n".join(f"[{sid}] {text}" for sid, _, text in entries),
        texts=tuple(text for _, _, text in entries),
    )


recordable_retrievals = st.lists(good_entries, min_size=0, max_size=4).map(_to_result)


@st.composite
def unrecordable_retrievals(draw) -> RetrievalResult:
    good = draw(st.lists(good_entries, min_size=0, max_size=3))
    bad = draw(st.lists(bad_entries, min_size=1, max_size=2))
    entries = draw(st.permutations(good + bad))
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
    """Returns the scripted RetrievalResult, or raises for retrieval_raises."""

    def __init__(
        self, script: dict[str, RetrievalResult], modes: dict[str, str]
    ) -> None:
        self._script = script
        self._modes = modes

    def retrieve(self, question: str, top_k: int) -> RetrievalResult:
        assert question in self._modes, f"unexpected retrieval question {question!r}"
        if self._modes[question] == "retrieval_raises":
            raise RuntimeError(f"scripted retrieval outage for {question!r}")
        return self._script[question]


class FailableGenerationClient:
    """Returns the scripted answer, or raises for generation_raises items."""

    def __init__(self, script: dict[str, str], modes: dict[str, str]) -> None:
        self._script = script
        self._modes = modes

    def generate(self, question: str, context: str, prompt_version: str) -> str:
        assert question in self._modes, f"unexpected generation question {question!r}"
        if self._modes[question] == "generation_raises":
            raise RuntimeError(f"scripted generation outage for {question!r}")
        return self._script[question]


class RecordingJudge:
    """Scripted `Judge` fake: records every (rubric, item id) it scores."""

    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = verdicts  # cycled per call
        self.calls: list[tuple[str, str]] = []  # (rubric name, item id)

    def score(self, rubric: Rubric, item, answer, retrieved) -> Verdict:
        self.calls.append((rubric.name, item.id))
        verdict = self._verdicts[(len(self.calls) - 1) % len(self._verdicts)]
        return Verdict(verdict=verdict, rationale=f"scripted {rubric.name}")


class RecordingReports:
    """ReportRepositoryLike fake."""

    def __init__(self) -> None:
        self.persisted: list[dict] = []

    def persist(self, report: dict) -> None:
        self.persisted.append(report)


# -- (b) strategies: mixed computed / not-computed scores ----------------------

OUTCOME_VALUES = (PASS, FAIL, ERROR)


@st.composite
def mixed_item_scores(draw) -> tuple[list[ItemGenerationScores], set[str]]:
    """A mix of computed and not-computed ItemGenerationScores.

    Returns (scores, computed_ids). Computed items carry the rubric set
    mandated for their category with arbitrary pass/fail/error outcomes;
    not-computed items are built via the production `not_computed(item)`
    exactly as the runner does for failed items.
    """
    n = draw(st.integers(min_value=1, max_value=10))
    scores: list[ItemGenerationScores] = []
    computed_ids: set[str] = set()

    for i in range(n):
        item = GoldenItem(
            id=f"item-{i:03d}",
            question=f"q{i}",
            language=draw(st.sampled_from(("ar", "en"))),
            category=draw(st.sampled_from(CATEGORIES)),
            expected_source_ids=(),
            counterpart_id=None,
        )
        if draw(st.booleans()):
            outcomes = tuple(
                RubricOutcome(
                    rubric=rubric.name,
                    outcome=draw(st.sampled_from(OUTCOME_VALUES)),
                    rationale="scripted",
                )
                for rubric in rubrics_for(item)
            )
            scores.append(
                ItemGenerationScores(
                    item_id=item.id,
                    category=item.category,
                    language=item.language,
                    computed=True,
                    outcomes=outcomes,
                )
            )
            computed_ids.add(item.id)
        else:
            scores.append(not_computed(item))

    return scores, computed_ids


def _expected_rates(group: list[ItemGenerationScores]) -> dict[str, MetricPassRate]:
    """Independent reference computation of per-rubric pass rates over a
    group of (already filtered) computed items."""
    counts: dict[str, dict[str, int]] = {}
    for item_scores in group:
        for outcome in item_scores.outcomes:
            per = counts.setdefault(outcome.rubric, {PASS: 0, FAIL: 0, ERROR: 0})
            per[outcome.outcome] += 1
    rates: dict[str, MetricPassRate] = {}
    for name, per in counts.items():
        denominator = per[PASS] + per[FAIL]
        rates[name] = MetricPassRate(
            pass_rate=per[PASS] / denominator if denominator else None,
            pass_count=per[PASS],
            fail_count=per[FAIL],
            error_count=per[ERROR],
        )
    return rates


# -- the property, side (a): through the runner ---------------------------------


class TestProperty24FailedItemsNeverReachTheJudge:
    @settings(max_examples=100)
    @given(
        data=datasets_with_failure_scripts(),
        config=eval_configs,
        verdicts=st.lists(st.sampled_from([PASS, FAIL]), min_size=1, max_size=3),
    )
    def test_judge_invoked_only_for_fully_successful_items(
        self, data, config, verdicts
    ):
        """For any mix of failing and succeeding items run through the
        runner with a real GenerationScorer, the judge is invoked exactly
        for the items that completed both steps — zero invocations for any
        failed item — and failed items carry not-computed generation
        metrics excluded from the aggregates (Req 8.9)."""
        dataset, modes, retrieval_script, answer_script = data
        judge = RecordingJudge(verdicts)
        runner = EvalRunner(
            FailableRetrievalClient(retrieval_script, modes),
            FailableGenerationClient(answer_script, modes),
            GenerationScorer(judge),
            RecordingReports(),
        )

        report = runner.run(config, dataset)

        ok_items = [i for i in dataset.items if modes[i.question] == "ok"]
        failed_ids = {i.id for i in dataset.items if modes[i.question] != "ok"}

        # The judge saw zero invocations for failed items...
        judged_ids = {item_id for _, item_id in judge.calls}
        assert judged_ids.isdisjoint(failed_ids)
        # ...and exactly the mandated (rubric, item) calls for the items
        # that completed both steps, in dataset order.
        assert judge.calls == [
            (rubric.name, item.id)
            for item in ok_items
            for rubric in rubrics_for(item)
        ]

        # Failed items are marked not-computed in the report; successful
        # items are computed.
        for item, entry in zip(dataset.items, report["per_item"]):
            expected_computed = item.id not in failed_ids
            assert entry["generation_scores"]["computed"] is expected_computed
            if not expected_computed:
                assert entry["generation_scores"]["outcomes"] == ()

        # The generation aggregates derive only from the computed items:
        # every group's verdict counts sum to exactly the judge calls made
        # for successful items — nothing from failed items leaks in.
        generation = report["aggregates"]["generation"]
        overall_total = sum(
            rate["pass_count"] + rate["fail_count"] + rate["error_count"]
            for rate in generation["overall"].values()
        )
        assert overall_total == len(judge.calls)

        # Groups exist only for categories/languages with computed items.
        assert set(generation["by_category"]) == {i.category for i in ok_items}
        assert set(generation["by_language"]) == {i.language for i in ok_items}

    # -- side (b): through aggregate directly -----------------------------------

    @settings(max_examples=100)
    @given(data=mixed_item_scores())
    def test_aggregate_counts_derive_only_from_computed_items(self, data):
        """For any mix of computed and not-computed ItemGenerationScores,
        every pass/fail/error count in the aggregates comes only from the
        computed items; not-computed items contribute nothing to any group
        (Req 8.9)."""
        scores, computed_ids = data
        computed = [s for s in scores if s.item_id in computed_ids]

        result = aggregate(scores)

        # per_item preserves everything (report completeness), but...
        assert result.per_item == tuple(scores)

        # ...overall counts match a reference computation over computed
        # items only.
        assert result.overall == _expected_rates(computed)

        # By-category and by-language groups exist exactly for the groups
        # holding at least one computed item, and each group's counts match
        # the reference computation over that group's computed items only.
        assert set(result.by_category) == {s.category for s in computed}
        assert set(result.by_language) == {s.language for s in computed}
        for category, rates in result.by_category.items():
            assert rates == _expected_rates(
                [s for s in computed if s.category == category]
            )
        for language, rates in result.by_language.items():
            assert rates == _expected_rates(
                [s for s in computed if s.language == language]
            )

    @settings(max_examples=100)
    @given(data=mixed_item_scores())
    def test_aggregate_unchanged_when_not_computed_items_removed(self, data):
        """Removing every not-computed item from the input leaves all
        aggregate groups byte-for-byte identical — the strongest form of
        'not-computed contributes nothing' (Req 8.9)."""
        scores, computed_ids = data
        computed_only = [s for s in scores if s.item_id in computed_ids]

        mixed = aggregate(scores)
        pure = aggregate(computed_only)

        assert mixed.overall == pure.overall
        assert mixed.by_category == pure.by_category
        assert mixed.by_language == pure.by_language
