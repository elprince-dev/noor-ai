"""compare(): pure two-report comparison (Req 9.3, 9.4, 9.5, 9.6).

`compare(report_a, report_b)` is a pure function over two loaded
`EvalReport` objects (design §compare.py). It produces a frozen
`ComparisonResult` carrying:

- `metric_diffs` — for every aggregate metric present in either report
  (retrieval recall@k / precision@k / MRR and generation per-rubric pass
  rates; overall, by category, and by language), the value from each run and
  the numeric difference `value_b - value_a` (Req 9.3). When a metric is
  missing or not computed on either side, its value is `None` and the diff
  is `None` — never a substituted number.
- `verdict_differences` — each (Golden_Item, rubric) whose pass/fail verdict
  differs between the runs, listed with the item id, rubric, and both
  verdicts (Req 9.4). A verdict absent on one side (item failed / rubric not
  scored in that run) is reported as `None`.
- `dataset_version_mismatch` — set when the two reports were produced from
  different Golden_Dataset versions; per-item verdict comparison is always
  restricted to the intersection of item ids, which under matching versions
  is simply every item (Req 9.5).

The unknown-run-id path (Req 9.6) belongs to loading: `ReportRepository.load`
raises `ReportNotFoundError` naming the missing id. `load_and_compare`
composes loading with `compare` so a comparison output is only ever produced
when both reports load — the CLI (task 11.6) surfaces the error.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evals.report import EvalReport, ReportRepository

# Retrieval aggregate metric values compared per group (MetricMeans fields;
# item_count is a count, not a metric).
_RETRIEVAL_METRICS = ("recall_at_k", "precision_at_k", "mrr")


@dataclass(frozen=True, slots=True)
class MetricDiff:
    """One aggregate metric: value from each run + numeric difference (Req 9.3).

    `metric` is a dotted path such as ``retrieval.overall.recall_at_k`` or
    ``generation.by_language.ar.faithfulness.pass_rate``. `diff` is
    ``value_b - value_a``, or `None` when either value is missing/not
    computed in its report.
    """

    metric: str
    value_a: float | None
    value_b: float | None
    diff: float | None


@dataclass(frozen=True, slots=True)
class VerdictDifference:
    """One (Golden_Item, rubric) whose verdict differs between runs (Req 9.4).

    A `None` verdict means the rubric has no recorded verdict in that run
    (item failed there, or the rubric was not scored for it).
    """

    item_id: str
    rubric: str
    verdict_a: str | None
    verdict_b: str | None


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """The full comparison of two Eval_Reports (Req 9.3–9.5)."""

    run_id_a: str
    run_id_b: str
    dataset_version_a: str
    dataset_version_b: str
    dataset_version_mismatch: bool
    metric_diffs: tuple[MetricDiff, ...]
    verdict_differences: tuple[VerdictDifference, ...]


def compare(report_a: EvalReport, report_b: EvalReport) -> ComparisonResult:
    """Pure comparison of two loaded Eval_Reports (design §compare.py).

    No I/O — loading (and the unknown-run-id error, Req 9.6) is the caller's
    concern; see `load_and_compare`.
    """
    mismatch = report_a.dataset_version != report_b.dataset_version
    return ComparisonResult(
        run_id_a=report_a.run_id,
        run_id_b=report_b.run_id,
        dataset_version_a=report_a.dataset_version,
        dataset_version_b=report_b.dataset_version,
        dataset_version_mismatch=mismatch,
        metric_diffs=_metric_diffs(report_a.aggregates, report_b.aggregates),
        verdict_differences=_verdict_differences(
            report_a.per_item, report_b.per_item
        ),
    )


def load_and_compare(
    repository: ReportRepository, run_id_a: str, run_id_b: str
) -> ComparisonResult:
    """Load both reports, then compare (Req 9.6).

    Raises:
        ReportNotFoundError: naming whichever run id has no persisted
            report — raised before any comparison output is produced.
    """
    report_a = EvalReport.from_dict(repository.load(run_id_a))
    report_b = EvalReport.from_dict(repository.load(run_id_b))
    return compare(report_a, report_b)


# --- aggregate metric flattening + diffing (Req 9.3) -----------------------


def _metric_diffs(
    aggregates_a: dict[str, Any], aggregates_b: dict[str, Any]
) -> tuple[MetricDiff, ...]:
    """Per-metric (value_a, value_b, diff) over the union of both reports'
    aggregate metrics, in sorted metric-path order."""
    flat_a = _flatten_aggregates(aggregates_a)
    flat_b = _flatten_aggregates(aggregates_b)
    diffs = []
    for metric in sorted(flat_a.keys() | flat_b.keys()):
        value_a = flat_a.get(metric)
        value_b = flat_b.get(metric)
        diff = value_b - value_a if value_a is not None and value_b is not None else None
        diffs.append(MetricDiff(metric=metric, value_a=value_a, value_b=value_b, diff=diff))
    return tuple(diffs)


def _flatten_aggregates(aggregates: dict[str, Any]) -> dict[str, float | None]:
    """Flatten one report's `aggregates` dict into ``{metric_path: value}``.

    Covers retrieval means and generation pass rates for overall,
    by_category, and by_language groups (Req 9.2's aggregate surface).
    """
    flat: dict[str, float | None] = {}

    retrieval = aggregates.get("retrieval") or {}
    _flatten_retrieval_group(flat, "retrieval.overall", retrieval.get("overall"))
    for grouping in ("by_category", "by_language"):
        for key, means in (retrieval.get(grouping) or {}).items():
            _flatten_retrieval_group(flat, f"retrieval.{grouping}.{key}", means)

    generation = aggregates.get("generation") or {}
    _flatten_generation_group(flat, "generation.overall", generation.get("overall"))
    for grouping in ("by_category", "by_language"):
        for key, rates in (generation.get(grouping) or {}).items():
            _flatten_generation_group(flat, f"generation.{grouping}.{key}", rates)

    return flat


def _flatten_retrieval_group(
    flat: dict[str, float | None], prefix: str, means: dict[str, Any] | None
) -> None:
    """Record one MetricMeans group (may be None when no items were applicable)."""
    if means is None:
        return
    for metric in _RETRIEVAL_METRICS:
        flat[f"{prefix}.{metric}"] = means.get(metric)


def _flatten_generation_group(
    flat: dict[str, float | None], prefix: str, rates: dict[str, Any] | None
) -> None:
    """Record one {rubric: MetricPassRate} group's pass rates."""
    for rubric, rate in (rates or {}).items():
        flat[f"{prefix}.{rubric}.pass_rate"] = rate.get("pass_rate")


# --- per-item verdict comparison (Req 9.4, 9.5) -----------------------------


def _verdict_differences(
    per_item_a: list[dict[str, Any]], per_item_b: list[dict[str, Any]]
) -> tuple[VerdictDifference, ...]:
    """Each (item, rubric) whose verdict differs, over the intersection of
    item ids (Req 9.4, 9.5), sorted by (item_id, rubric)."""
    verdicts_a = _item_verdicts(per_item_a)
    verdicts_b = _item_verdicts(per_item_b)
    differences = []
    for item_id in sorted(verdicts_a.keys() & verdicts_b.keys()):
        item_a, item_b = verdicts_a[item_id], verdicts_b[item_id]
        for rubric in sorted(item_a.keys() | item_b.keys()):
            verdict_a = item_a.get(rubric)
            verdict_b = item_b.get(rubric)
            if verdict_a != verdict_b:
                differences.append(
                    VerdictDifference(
                        item_id=item_id,
                        rubric=rubric,
                        verdict_a=verdict_a,
                        verdict_b=verdict_b,
                    )
                )
    return tuple(differences)


def _item_verdicts(per_item: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """``{item_id: {rubric: verdict}}`` from one report's per_item records.

    Items whose generation metrics were not computed (failed during
    execution) contribute an empty verdict map — their rubrics show up as
    `None` against a run that did score them.
    """
    verdicts: dict[str, dict[str, str]] = {}
    for record in per_item:
        scores = record.get("generation_scores") or {}
        outcomes = scores.get("outcomes") or ()
        verdicts[record["item_id"]] = {
            outcome["rubric"]: outcome["outcome"] for outcome in outcomes
        }
    return verdicts
