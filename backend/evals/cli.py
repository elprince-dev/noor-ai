"""CLI composition root: `python -m evals run|compare|triage ...` (design §cli.py).

This is the only module that constructs the production object graph
(Req 6.6): every other harness module receives its collaborators through
constructors, so tests use in-memory fakes while this file injects the real
adapters against deployed AWS resources.

Subcommands:

- ``run --config <path>`` — load and validate the Eval_Config (abort with a
  clear message on `EvalConfigError`, Req 6.8, 8.8), load the Golden_Dataset
  via `DatasetLoader` (abort on `DatasetValidationError` / undeterminable
  version `DatasetVersionError` — both before any Golden_Item executes,
  Req 4.11, 5.2, 5.4), then construct
  ``EvalRunner(SrcRetrievalClient, SrcGenerationClient, GenerationScorer(NovaJudge), ReportRepository)``
  and run, printing the assigned run id.
- ``compare <run_a> <run_b>`` — load both persisted Eval_Reports and print
  the comparison (`ReportNotFoundError` names the missing id, Req 9.6).
- ``triage ...`` — delegates to `evals.triage.run_triage` (task 16.1).

All aborts print ``error: ...`` to stderr and exit non-zero; usage errors
exit 2 (argparse convention).

Relative `dataset_path` / `results_dir` values are resolved against the
config file's directory first (so `evals/config.yaml` can say
``data/golden_dataset.jsonl``), falling back to the current working
directory (so the dataclass defaults like ``evals/results`` work when
running from `backend/`).
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.compare import ComparisonResult, load_and_compare
from evals.dataset import DatasetLoader, DatasetValidationError, DatasetVersionError
from evals.eval_config import EvalConfigError, load_config
from evals.report import ReportNotFoundError, ReportRepository

DEFAULT_RESULTS_DIR = "evals/results"


# -- path resolution ----------------------------------------------------------


def resolve_input_path(raw: str, config_dir: Path) -> Path:
    """Resolve a config-supplied *input* path (must already exist to be useful).

    Absolute paths pass through. A relative path is tried against the config
    file's directory first (``dataset_path: data/golden_dataset.jsonl`` in
    ``evals/config.yaml``), then falls back to the current working directory
    (the dataclass default ``evals/data/golden_dataset.jsonl`` from
    ``backend/``).
    """
    path = Path(raw)
    if path.is_absolute():
        return path
    candidate = config_dir / path
    if candidate.exists():
        return candidate
    return path  # cwd-relative; loader reports a clear error if missing


def resolve_results_dir(raw: str, config_dir: Path) -> Path:
    """Resolve the *output* results directory (may not exist yet).

    Preference order: an existing config-dir-relative directory, an existing
    cwd-relative directory, then whichever candidate's parent already exists
    (config dir first) so ``results_dir: results`` in ``evals/config.yaml``
    creates ``evals/results`` rather than a stray ``backend/results``.
    """
    path = Path(raw)
    if path.is_absolute():
        return path
    candidate = config_dir / path
    if candidate.is_dir():
        return candidate
    if path.is_dir():
        return path
    if candidate.parent.is_dir():
        return candidate
    return path


# -- run ----------------------------------------------------------------------


def _cmd_run(config_path: str) -> int:
    """Execute one full eval run; every abort happens before any item runs."""
    # 1. Eval_Config: abort on invalid, naming the offending parameter
    #    (Req 6.8) — including a judge from the generation model's family
    #    (Req 8.8).
    try:
        config = load_config(config_path)
    except EvalConfigError as exc:
        print(f"error: invalid Eval_Config: {exc}", file=sys.stderr)
        return 1

    config_dir = Path(config_path).resolve().parent
    dataset_path = resolve_input_path(config.dataset_path, config_dir)

    # 2. Golden_Dataset: version is resolved and validation runs inside
    #    `load`, so an invalid dataset (Req 4.11) or undeterminable version
    #    (Req 5.4) aborts here — before any Golden_Item executes (Req 5.2).
    try:
        dataset = DatasetLoader().load(dataset_path)
    except (DatasetVersionError, DatasetValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 3. Only now construct the AWS-facing production adapters (Req 6.6).
    #    Imported lazily so config/dataset validation and `--help` never
    #    touch AWS SDK setup.
    from evals.judge import NovaJudge
    from evals.metrics.generation import GenerationScorer
    from evals.pipeline import SrcGenerationClient, SrcRetrievalClient
    from evals.runner import EvalRunner

    reports = ReportRepository(resolve_results_dir(config.results_dir, config_dir))
    runner = EvalRunner(
        retrieval=SrcRetrievalClient(),
        generator=SrcGenerationClient(config.model_id),
        scorer=GenerationScorer(NovaJudge(config.judge_model_id)),
        reports=reports,
    )

    print(
        f"running eval: {len(dataset.items)} items, "
        f"dataset version {dataset.version}"
    )
    report = runner.run(config, dataset)

    counts = report["counts"]
    print(f"run complete: {reports.last_run_id}")
    print(f"  succeeded: {counts['succeeded']}  failed: {counts['failed']}")
    return 0


# -- compare ------------------------------------------------------------------


def _fmt(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.4f}" if signed else f"{value:.4f}"


def _print_comparison(result: ComparisonResult) -> None:
    """Print the ComparisonResult: metric diffs then verdict differences."""
    print(f"run A: {result.run_id_a}  (dataset {result.dataset_version_a})")
    print(f"run B: {result.run_id_b}  (dataset {result.dataset_version_b})")
    if result.dataset_version_mismatch:
        print(
            "warning: dataset versions differ — per-item verdicts are "
            "compared over the intersection of item ids only"
        )

    print("\naggregate metric diffs (A -> B, diff = B - A):")
    if not result.metric_diffs:
        print("  (no aggregate metrics in either report)")
    for diff in result.metric_diffs:
        print(
            f"  {diff.metric}: {_fmt(diff.value_a)} -> {_fmt(diff.value_b)}"
            f"  (diff {_fmt(diff.diff, signed=True)})"
        )

    print("\nper-item verdict differences:")
    if not result.verdict_differences:
        print("  (none)")
    for vd in result.verdict_differences:
        print(
            f"  {vd.item_id} [{vd.rubric}]: "
            f"{vd.verdict_a or 'not scored'} -> {vd.verdict_b or 'not scored'}"
        )


def _cmd_compare(run_a: str, run_b: str, results_dir: str) -> int:
    repository = ReportRepository(results_dir)
    try:
        result = load_and_compare(repository, run_a, run_b)
    except ReportNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_comparison(result)
    return 0


# -- argument parsing + entry point -------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="Noor-AI offline eval harness (run from backend/).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="execute a full eval run against deployed AWS resources"
    )
    run_parser.add_argument(
        "--config",
        required=True,
        help="path to the Eval_Config YAML file (e.g. evals/config.yaml)",
    )

    compare_parser = subparsers.add_parser(
        "compare", help="compare two persisted Eval_Reports"
    )
    compare_parser.add_argument("run_a", help="run id of the baseline report")
    compare_parser.add_argument("run_b", help="run id of the candidate report")
    compare_parser.add_argument(
        "--results-dir",
        default=DEFAULT_RESULTS_DIR,
        help=f"directory holding persisted runs (default: {DEFAULT_RESULTS_DIR})",
    )

    triage_parser = subparsers.add_parser(
        "triage", help="triage down-rated feedback: list | draft <request_id>"
    )
    triage_parser.add_argument(
        "triage_args",
        nargs="*",
        help="triage subcommand: list | draft <request_id>",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args.config)
    if args.command == "compare":
        return _cmd_compare(args.run_a, args.run_b, args.results_dir)
    # triage owns its own parsing, output, and exit codes (task 16.1);
    # imported lazily so run/compare never touch the src repositories.
    from evals.triage import run_triage

    return run_triage(args.triage_args)


if __name__ == "__main__":
    raise SystemExit(main())
