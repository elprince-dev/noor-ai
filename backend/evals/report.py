"""EvalReport model + ReportRepository: filesystem persist/load (Req 5.3, 6.7, 9.1, 9.2).

`ReportRepository(results_dir)` is the only class touching the results
filesystem (design §report.py):

- `persist(report)` assigns a fresh `run_id`
  (`"{UTC:%Y%m%dT%H%M%SZ}-{uuid4hex[:8]}"`), injects it into the stored
  JSON, and writes `results/{run_id}/report.json`. It refuses to overwrite
  an existing path — on collision it regenerates the run id — and never
  mutates or deletes previously persisted reports (Req 9.1). It returns the
  assigned run id so callers (the CLI, task 11.6) can print it; the runner's
  `ReportRepositoryLike` protocol ignores the return value.
- `load(run_id)` reads the report back as a dict or raises
  `ReportNotFoundError` naming the id (Req 9.6 groundwork for compare.py).

The report dict itself is the machine-readable format (Req 9.2): `run_id`,
`config`, `dataset_version`, `completed_at`, `aggregates` (retrieval +
generation, overall/category/language), `per_item` (verdicts with judge
rationales, or failure records), and `counts {succeeded, failed}` — exactly
the payload `EvalRunner.run()` assembles, plus the injected `run_id`.
`EvalReport` is a thin typed wrapper over that dict for consumers such as
`compare()` (task 11.4) that want attribute access instead of key lookups.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReportNotFoundError(Exception):
    """No persisted Eval_Report exists for the requested run id."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"no persisted Eval_Report found for run id {run_id!r}")


def generate_run_id(now: datetime | None = None) -> str:
    """A run identifier: UTC timestamp + 8 hex chars of uuid4 entropy.

    Format: ``{UTC:%Y%m%dT%H%M%SZ}-{uuid4hex[:8]}`` (design §report.py).
    """
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


# Fields Req 9.2 mandates in every stored Eval_Report.
_REPORT_FIELDS = (
    "run_id",
    "config",
    "dataset_version",
    "completed_at",
    "aggregates",
    "per_item",
    "counts",
)


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Typed view over one persisted Eval_Report (Req 9.2).

    The canonical machine-readable artifact is the JSON dict written by
    `ReportRepository.persist`; this wrapper gives downstream consumers
    (compare.py) attribute access to the mandated fields.
    """

    run_id: str
    config: dict[str, Any]
    dataset_version: str
    completed_at: str
    aggregates: dict[str, Any]  # {"retrieval": ..., "generation": ...}
    per_item: list[dict[str, Any]]  # verdicts + rationales, or failure records
    counts: dict[str, int]  # {"succeeded": n, "failed": m}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalReport":
        """Build the typed view from a stored report dict.

        Raises:
            KeyError: a Req 9.2-mandated field is missing from the dict.
        """
        return cls(**{field: data[field] for field in _REPORT_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        """The JSON-serializable report payload, run_id first."""
        return {field: getattr(self, field) for field in _REPORT_FIELDS}


class ReportRepository:
    """Append-only filesystem store for Eval_Reports (Req 9.1).

    Satisfies the runner's `ReportRepositoryLike` protocol; `persist`
    additionally returns the assigned run id for the CLI.
    """

    def __init__(
        self,
        results_dir: str | Path,
        run_id_factory: Callable[[], str] = generate_run_id,
    ) -> None:
        self._results_dir = Path(results_dir)
        self._run_id_factory = run_id_factory
        self.last_run_id: str | None = None

    def persist(self, report: dict[str, Any]) -> str:
        """Write `results/{run_id}/report.json` under a fresh unique run id.

        Generates a run id, regenerating whenever the target path already
        exists (collision), so no previously persisted report is ever
        overwritten, mutated, or deleted (Req 9.1). The input dict is not
        mutated; the run id is injected into the stored copy (Req 9.2).

        Returns:
            The assigned run id (also recorded as `last_run_id`).
        """
        while True:
            run_id = self._run_id_factory()
            run_dir = self._results_dir / run_id
            if run_dir.exists():
                continue  # collision — regenerate, never touch existing runs
            try:
                run_dir.mkdir(parents=True)
                # "x" = exclusive create: refuses to overwrite even under a
                # concurrent-writer race the exists() check missed.
                with (run_dir / "report.json").open("x", encoding="utf-8") as fh:
                    json.dump(
                        {"run_id": run_id, **report},
                        fh,
                        ensure_ascii=False,  # Arabic text stays readable
                        indent=2,
                    )
            except FileExistsError:
                continue
            self.last_run_id = run_id
            return run_id

    def load(self, run_id: str) -> dict[str, Any]:
        """Read back the persisted report for `run_id`.

        Raises:
            ReportNotFoundError: naming the id, when no report exists for it.
        """
        path = self._results_dir / run_id / "report.json"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ReportNotFoundError(run_id) from exc
        return json.loads(text)
