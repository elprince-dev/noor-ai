"""Property 27: Report round trip (design.md).

*For any* completed run outcome, the persisted Eval_Report parses back with
its run identifier, Eval_Config, Golden_Dataset version, completion
timestamp, aggregate metrics, per-item verdicts with judge rationales, and
succeeded/failed counts all intact and equal to the in-memory values.

**Validates: Requirements 5.3, 6.7, 9.2**

Pure filesystem Hypothesis test against tempfile directories — no AWS calls.
Report payloads are generated in the shape `EvalRunner.run()` assembles
(runner.py): an `EvalConfig` dict, the dataset version, a completion
timestamp, retrieval + generation aggregates (overall / by category / by
language), and per-item records — succeeded items carrying retrieved
(Source_ID, score) pairs, the generated answer, and judge verdicts with
rationales; failed items carrying the failing step and error description.
Arabic text is generated throughout so non-ASCII content is proven to
survive persistence.

`deadline=None` because each example performs real file I/O.
"""
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from evals.report import EvalReport, ReportRepository

# -- strategies ----------------------------------------------------------------

# Free text in both scripts (Arabic content must survive persistence intact).
any_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
    ),
    max_size=40,
)

nonempty_text = any_text.filter(lambda s: len(s) > 0)

scores = st.floats(allow_nan=False, allow_infinity=False, width=32)

# A metric value as aggregates carry them: computed float or not-computed None.
metric_values = st.one_of(st.none(), scores)

rubric_names = st.sampled_from(
    ["faithfulness", "citation_accuracy", "answer_relevancy", "abstention"]
)

# One per-rubric outcome as `GenerationScorer` records it (RubricOutcome:
# rubric name, pass/fail judge verdict or "error" after the failed retry,
# and the judge rationale) — the shape `EvalRunner.run()` serializes via
# `asdict(ItemGenerationScores)` into each per_item record.
rubric_outcomes = st.fixed_dictionaries(
    {
        "rubric": rubric_names,
        "outcome": st.sampled_from(["pass", "fail", "error"]),
        "rationale": any_text,
    }
)

categories = st.sampled_from(
    ["direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus"]
)
languages = st.sampled_from(["ar", "en"])

# Aggregates block: overall / by_category / by_language metric groups.
metric_groups = st.dictionaries(nonempty_text, metric_values, max_size=3)
aggregate_blocks = st.fixed_dictionaries(
    {
        "overall": metric_groups,
        "by_category": st.dictionaries(nonempty_text, metric_groups, max_size=2),
        "by_language": st.dictionaries(nonempty_text, metric_groups, max_size=2),
    }
)


@st.composite
def succeeded_items(draw) -> dict:
    """A per-item record for an item that completed both steps (Req 6.3):
    retrieved Source_IDs with scores, the answer, and judge verdicts with
    rationales recorded together, in the `asdict(ItemGenerationScores)`
    shape the runner serializes."""
    item_id = draw(nonempty_text)
    return {
        "item_id": item_id,
        "retrieved": draw(
            st.lists(st.tuples(nonempty_text, scores).map(list), max_size=4)
        ),
        "answer": draw(any_text),
        "failed": False,
        "failing_step": None,
        "error": None,
        "generation_scores": {
            "item_id": item_id,
            "category": draw(categories),
            "language": draw(languages),
            "computed": True,
            "outcomes": draw(
                st.lists(
                    rubric_outcomes,
                    max_size=4,
                    unique_by=lambda outcome: outcome["rubric"],
                )
            ),
        },
    }


@st.composite
def failed_items(draw) -> dict:
    """A per-item failure record (Req 6.5): failing step + error description;
    retrieval results retained on generation failure, generation scores
    not computed (`not_computed(item)` — empty outcomes)."""
    failing_step = draw(st.sampled_from(["retrieval", "generation"]))
    retrieved = (
        draw(st.lists(st.tuples(nonempty_text, scores).map(list), max_size=4))
        if failing_step == "generation"
        else []
    )
    item_id = draw(nonempty_text)
    return {
        "item_id": item_id,
        "retrieved": retrieved,
        "answer": None,
        "failed": True,
        "failing_step": failing_step,
        "error": draw(any_text),
        "generation_scores": {
            "item_id": item_id,
            "category": draw(categories),
            "language": draw(languages),
            "computed": False,
            "outcomes": [],
        },
    }


@st.composite
def reports(draw) -> dict:
    """One completed-run report payload as `EvalRunner.run()` assembles it —
    every Req 9.2 field except `run_id`, which `persist` injects. Counts are
    derived from the per-item records, as the runner derives them."""
    per_item = draw(
        st.lists(st.one_of(succeeded_items(), failed_items()), max_size=5)
    )
    return {
        "config": draw(
            st.fixed_dictionaries(
                {
                    "model_id": nonempty_text,
                    "retrieval_top_k": st.integers(1, 20),
                    "prompt_version": st.sampled_from(["v1", "v2"]),
                    "judge_model_id": nonempty_text,
                    "dataset_path": any_text,
                    "results_dir": any_text,
                }
            )
        ),
        "dataset_version": draw(nonempty_text),
        "completed_at": draw(nonempty_text),
        "aggregates": {
            "retrieval": draw(aggregate_blocks),
            "generation": draw(aggregate_blocks),
        },
        "per_item": per_item,
        "counts": {
            "succeeded": sum(1 for item in per_item if not item["failed"]),
            "failed": sum(1 for item in per_item if item["failed"]),
        },
    }


class TestProperty27ReportRoundTrip:
    @settings(max_examples=100, deadline=None)
    @given(report=reports())
    def test_persist_then_load_preserves_every_field(self, report):
        """For any completed run outcome, the persisted report parses back
        with run_id, config, dataset version, completion timestamp,
        aggregates, per-item records, and counts all equal to the in-memory
        values (Req 5.3, 6.7, 9.2)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = ReportRepository(tmp)
            run_id = repo.persist(report)

            loaded = repo.load(run_id)

            # The whole payload survives, with the assigned run id injected.
            assert loaded == {"run_id": run_id, **report}
            # Each Req 9.2-mandated field individually equals the in-memory value.
            assert loaded["run_id"] == run_id
            assert loaded["config"] == report["config"]
            assert loaded["dataset_version"] == report["dataset_version"]  # Req 5.3
            assert loaded["completed_at"] == report["completed_at"]
            assert loaded["aggregates"] == report["aggregates"]
            assert loaded["per_item"] == report["per_item"]  # Req 6.7
            assert loaded["counts"] == report["counts"]

    @settings(max_examples=100, deadline=None)
    @given(report=reports())
    def test_per_item_verdicts_and_rationales_survive(self, report):
        """Per-item judge verdicts with their rationales, retrieved
        (Source_ID, score) pairs, answers, and failure records each survive
        the round trip value-for-value (Req 6.7, 9.2)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = ReportRepository(tmp)
            run_id = repo.persist(report)

            loaded = repo.load(run_id)

            assert len(loaded["per_item"]) == len(report["per_item"])
            for stored, original in zip(loaded["per_item"], report["per_item"]):
                assert stored["item_id"] == original["item_id"]
                assert stored["retrieved"] == original["retrieved"]
                assert stored["answer"] == original["answer"]
                assert stored["failed"] == original["failed"]
                assert stored["failing_step"] == original["failing_step"]
                assert stored["error"] == original["error"]
                # Verdicts with judge rationales, rubric by rubric.
                assert (
                    stored["generation_scores"]["outcomes"]
                    == original["generation_scores"]["outcomes"]
                )
                assert (
                    stored["generation_scores"]["computed"]
                    == original["generation_scores"]["computed"]
                )

    @settings(max_examples=100, deadline=None)
    @given(report=reports())
    def test_typed_wrapper_round_trips_the_loaded_report(self, report):
        """`EvalReport.from_dict` over the loaded dict exposes every mandated
        field with the persisted values, and `to_dict` reproduces the loaded
        payload exactly (Req 9.2)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = ReportRepository(tmp)
            run_id = repo.persist(report)

            loaded = repo.load(run_id)
            typed = EvalReport.from_dict(loaded)

            assert typed.run_id == run_id
            assert typed.config == report["config"]
            assert typed.dataset_version == report["dataset_version"]
            assert typed.completed_at == report["completed_at"]
            assert typed.aggregates == report["aggregates"]
            assert typed.per_item == report["per_item"]
            assert typed.counts == report["counts"]
            assert typed.to_dict() == loaded
