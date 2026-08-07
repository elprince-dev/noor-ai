"""Property 28: Comparison correctness (design.md).

*For any* pair of persisted Eval_Reports, the comparison output lists every
aggregate metric with both values and their exact numeric difference,
identifies exactly the Golden_Items whose verdicts differ (with both
verdicts); when the reports' Golden_Dataset versions differ, the output
flags the mismatch and restricts per-item comparison to items present in
both; and a comparison naming a run identifier with no persisted report
fails with an error naming that identifier and produces no output.

**Validates: Requirements 9.3, 9.4, 9.5, 9.6**

Pure Hypothesis test over `compare()` for the metric/verdict semantics
(Req 9.3–9.5) and a tempfile-backed `ReportRepository` for the
`load_and_compare` unknown-run-id path (Req 9.6) — no AWS calls. Report
payloads follow the shape `EvalRunner.run()` assembles: aggregates carrying
retrieval `MetricMeans` groups and generation `MetricPassRate` groups
(overall / by category / by language), and per-item records whose
`generation_scores` are serialized `ItemGenerationScores` with per-rubric
`outcomes`. Arabic identifiers are generated so non-ASCII item ids are
proven to compare correctly.

`deadline=None` on the repository test because each example performs real
file I/O.
"""
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.compare import compare, load_and_compare
from evals.report import EvalReport, ReportNotFoundError, ReportRepository

# -- strategies ----------------------------------------------------------------

# Small pools so the two reports overlap (and diverge) in interesting ways.
ITEM_ID_POOL = ("item-1", "item-2", "item-3", "سؤال-٤", "item-5", "item-6")
RUBRICS = ("faithfulness", "citation_accuracy", "answer_relevancy", "abstention")
CATEGORIES = ("direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus")
LANGUAGES = ("ar", "en")
DATASET_VERSIONS = ("1.0.0+aaaaaaaaaaaa", "1.0.0+bbbbbbbbbbbb", "1.1.0+cccccccccccc")

metric_floats = st.floats(allow_nan=False, allow_infinity=False, width=32)

# One retrieval MetricMeans group as asdict() serializes it.
metric_means = st.fixed_dictionaries(
    {
        "recall_at_k": metric_floats,
        "precision_at_k": metric_floats,
        "mrr": metric_floats,
        "item_count": st.integers(1, 100),
    }
)

# One retrieval aggregates block: overall may be None (zero applicable items).
retrieval_blocks = st.fixed_dictionaries(
    {
        "overall": st.none() | metric_means,
        "by_category": st.dictionaries(
            st.sampled_from(CATEGORIES), metric_means, max_size=3
        ),
        "by_language": st.dictionaries(
            st.sampled_from(LANGUAGES), metric_means, max_size=2
        ),
    }
)

# One generation MetricPassRate as asdict() serializes it; pass_rate may be
# None (zero pass+fail verdicts — errors never substitute, Req 8.7).
pass_rates = st.fixed_dictionaries(
    {
        "pass_rate": st.none() | metric_floats,
        "pass_count": st.integers(0, 50),
        "fail_count": st.integers(0, 50),
        "error_count": st.integers(0, 50),
    }
)

generation_groups = st.dictionaries(
    st.sampled_from(RUBRICS), pass_rates, max_size=4
)

generation_blocks = st.fixed_dictionaries(
    {
        "overall": generation_groups,
        "by_category": st.dictionaries(
            st.sampled_from(CATEGORIES), generation_groups, max_size=3
        ),
        "by_language": st.dictionaries(
            st.sampled_from(LANGUAGES), generation_groups, max_size=2
        ),
    }
)


@st.composite
def per_item_records(draw, item_id: str) -> dict:
    """One per-item record in the runner's serialized shape: succeeded items
    carry per-rubric outcomes; failed items carry `computed=False` with an
    empty outcomes list (`not_computed`, Req 8.9)."""
    computed = draw(st.booleans())
    outcomes = (
        draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        "rubric": st.sampled_from(RUBRICS),
                        "outcome": st.sampled_from(["pass", "fail", "error"]),
                        "rationale": st.text(max_size=20),
                    }
                ),
                max_size=4,
                unique_by=lambda outcome: outcome["rubric"],
            )
        )
        if computed
        else []
    )
    return {
        "item_id": item_id,
        "retrieved": [],
        "answer": "answer" if computed else None,
        "failed": not computed,
        "failing_step": None if computed else "generation",
        "error": None if computed else "boom",
        "generation_scores": {
            "item_id": item_id,
            "category": draw(st.sampled_from(CATEGORIES)),
            "language": draw(st.sampled_from(LANGUAGES)),
            "computed": computed,
            "outcomes": outcomes,
        },
    }


@st.composite
def report_payloads(draw, dataset_version: str) -> dict:
    """One report payload (every Req 9.2 field except `run_id`) with unique
    item ids drawn from the shared pool."""
    ids = draw(
        st.lists(st.sampled_from(ITEM_ID_POOL), unique=True, max_size=len(ITEM_ID_POOL))
    )
    per_item = [draw(per_item_records(item_id)) for item_id in ids]
    return {
        "config": {
            "model_id": "anthropic.claude-haiku",
            "retrieval_top_k": 5,
            "prompt_version": "v1",
            "judge_model_id": "amazon.nova-pro",
            "dataset_path": "data/golden_dataset.jsonl",
            "results_dir": "results",
        },
        "dataset_version": dataset_version,
        "completed_at": "2025-01-01T00:00:00+00:00",
        "aggregates": {
            "retrieval": draw(retrieval_blocks),
            "generation": draw(generation_blocks),
        },
        "per_item": per_item,
        "counts": {
            "succeeded": sum(1 for item in per_item if not item["failed"]),
            "failed": sum(1 for item in per_item if item["failed"]),
        },
    }


@st.composite
def report_pairs(draw, same_version: bool) -> tuple[EvalReport, EvalReport]:
    """Two loaded Eval_Reports, with matching or differing dataset versions."""
    version_a = draw(st.sampled_from(DATASET_VERSIONS))
    version_b = (
        version_a
        if same_version
        else draw(st.sampled_from([v for v in DATASET_VERSIONS if v != version_a]))
    )
    report_a = EvalReport.from_dict(
        {"run_id": "run-a", **draw(report_payloads(version_a))}
    )
    report_b = EvalReport.from_dict(
        {"run_id": "run-b", **draw(report_payloads(version_b))}
    )
    return report_a, report_b


# -- independent oracles -------------------------------------------------------

_RETRIEVAL_METRICS = ("recall_at_k", "precision_at_k", "mrr")


def expected_metric_values(aggregates: dict) -> dict:
    """{metric_path: value} for one report's aggregates — the aggregate
    metric surface Req 9.3 mandates in the comparison output."""
    flat: dict = {}
    retrieval = aggregates["retrieval"]
    groups = [("retrieval.overall", retrieval["overall"])]
    for grouping in ("by_category", "by_language"):
        groups += [
            (f"retrieval.{grouping}.{key}", means)
            for key, means in retrieval[grouping].items()
        ]
    for prefix, means in groups:
        if means is None:
            continue
        for metric in _RETRIEVAL_METRICS:
            flat[f"{prefix}.{metric}"] = means[metric]

    generation = aggregates["generation"]
    gen_groups = [("generation.overall", generation["overall"])]
    for grouping in ("by_category", "by_language"):
        gen_groups += [
            (f"generation.{grouping}.{key}", rates)
            for key, rates in generation[grouping].items()
        ]
    for prefix, rates in gen_groups:
        for rubric, rate in rates.items():
            flat[f"{prefix}.{rubric}.pass_rate"] = rate["pass_rate"]
    return flat


def verdict_map(per_item: list) -> dict:
    """{item_id: {rubric: outcome}} — an item's recorded verdicts (empty for
    not-computed items, whose rubrics show as None against a scoring run)."""
    return {
        record["item_id"]: {
            outcome["rubric"]: outcome["outcome"]
            for outcome in record["generation_scores"]["outcomes"]
        }
        for record in per_item
    }


def expected_verdict_differences(report_a: EvalReport, report_b: EvalReport) -> set:
    """Exactly the (item, rubric) pairs whose verdicts differ, over the
    intersection of item ids (Req 9.4, 9.5)."""
    verdicts_a = verdict_map(report_a.per_item)
    verdicts_b = verdict_map(report_b.per_item)
    differences = set()
    for item_id in verdicts_a.keys() & verdicts_b.keys():
        item_a, item_b = verdicts_a[item_id], verdicts_b[item_id]
        for rubric in item_a.keys() | item_b.keys():
            if item_a.get(rubric) != item_b.get(rubric):
                differences.add(
                    (item_id, rubric, item_a.get(rubric), item_b.get(rubric))
                )
    return differences


# -- tests ----------------------------------------------------------------------


class TestProperty28ComparisonCorrectness:
    @settings(max_examples=100)
    @given(pair=report_pairs(same_version=True))
    def test_every_aggregate_metric_diffed_with_exact_difference(self, pair):
        """For each aggregate metric present in either report, the comparison
        lists the value from each run and the exact numeric difference
        value_b - value_a; a value missing or not computed on either side
        yields a None value and a None diff — never a substituted number
        (Req 9.3)."""
        report_a, report_b = pair
        expected_a = expected_metric_values(report_a.aggregates)
        expected_b = expected_metric_values(report_b.aggregates)

        result = compare(report_a, report_b)

        diffs = {diff.metric: diff for diff in result.metric_diffs}
        # Exactly the union of both reports' aggregate metrics, no more, no less.
        assert set(diffs) == set(expected_a) | set(expected_b)
        for metric, diff in diffs.items():
            assert diff.value_a == expected_a.get(metric)
            assert diff.value_b == expected_b.get(metric)
            if diff.value_a is not None and diff.value_b is not None:
                assert diff.diff == diff.value_b - diff.value_a
            else:
                assert diff.diff is None

    @settings(max_examples=100)
    @given(pair=report_pairs(same_version=True))
    def test_exactly_the_differing_verdicts_are_listed(self, pair):
        """Exactly the (Golden_Item, rubric) pairs whose verdicts differ
        between the runs appear in the output, each with the item id and
        both verdicts; identical verdicts never appear (Req 9.4). Matching
        dataset versions never flag a mismatch (Req 9.5)."""
        report_a, report_b = pair

        result = compare(report_a, report_b)

        actual = {
            (diff.item_id, diff.rubric, diff.verdict_a, diff.verdict_b)
            for diff in result.verdict_differences
        }
        assert actual == expected_verdict_differences(report_a, report_b)
        assert result.dataset_version_mismatch is False
        assert result.run_id_a == report_a.run_id
        assert result.run_id_b == report_b.run_id

    @settings(max_examples=100)
    @given(pair=report_pairs(same_version=False))
    def test_version_mismatch_flagged_and_comparison_restricted_to_intersection(
        self, pair
    ):
        """Different Golden_Dataset versions set the mismatch flag, and
        per-item verdict comparison covers only items present in both
        reports (Req 9.5) — with both verdicts still correct (Req 9.4)."""
        report_a, report_b = pair

        result = compare(report_a, report_b)

        assert result.dataset_version_mismatch is True
        assert result.dataset_version_a == report_a.dataset_version
        assert result.dataset_version_b == report_b.dataset_version

        common_ids = {record["item_id"] for record in report_a.per_item} & {
            record["item_id"] for record in report_b.per_item
        }
        assert all(
            diff.item_id in common_ids for diff in result.verdict_differences
        )
        actual = {
            (diff.item_id, diff.rubric, diff.verdict_a, diff.verdict_b)
            for diff in result.verdict_differences
        }
        assert actual == expected_verdict_differences(report_a, report_b)

    @settings(max_examples=100, deadline=None)
    @given(
        payload_a=report_payloads("1.0.0+aaaaaaaaaaaa"),
        payload_b=report_payloads("1.0.0+aaaaaaaaaaaa"),
        missing_id=st.text(
            alphabet=st.one_of(
                st.characters(categories=("Ll", "Lu", "Nd")),  # a-z, A-Z, 0-9 &c.
                st.characters(min_codepoint=0x0621, max_codepoint=0x064A),  # Arabic
            ),
            min_size=1,
            max_size=20,
        ).filter(lambda s: s not in (".", "..")),
    )
    def test_unknown_run_id_errors_naming_the_id_with_no_output(
        self, payload_a, payload_b, missing_id
    ):
        """Via `load_and_compare` over a tempdir-backed ReportRepository: a
        run identifier with no persisted report raises an error naming that
        identifier and produces no comparison output, in either position;
        two known identifiers compare normally (Req 9.6)."""
        with tempfile.TemporaryDirectory() as tmp:
            repository = ReportRepository(tmp)
            run_id_a = repository.persist(payload_a)
            run_id_b = repository.persist(payload_b)
            assert missing_id not in (run_id_a, run_id_b)

            # Unknown id in either position: error names exactly that id,
            # and the raise means no ComparisonResult is ever produced.
            with pytest.raises(ReportNotFoundError) as exc_info:
                load_and_compare(repository, run_id_a, missing_id)
            assert exc_info.value.run_id == missing_id
            assert missing_id in str(exc_info.value)

            with pytest.raises(ReportNotFoundError) as exc_info:
                load_and_compare(repository, missing_id, run_id_b)
            assert exc_info.value.run_id == missing_id
            assert missing_id in str(exc_info.value)

            # Both ids known: loading + comparison succeeds end to end.
            result = load_and_compare(repository, run_id_a, run_id_b)
            assert result.run_id_a == run_id_a
            assert result.run_id_b == run_id_b
            assert result.dataset_version_mismatch is False
