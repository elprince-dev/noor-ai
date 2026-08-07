"""Feedback triage into the Golden_Dataset (Req 12.1, 12.2, 12.3, 12.5, 12.6).

`TriageService` turns negatively-rated production queries into draft
Golden_Items:

- `list_down_rated()` — every down-rated Feedback_Record newest-first, each
  joined with the query/response from its linked Trace via
  `TraceRepository.get(request_id)` (Req 12.1, 12.2). A missing Trace (never
  persisted for a failed request, or expired past retention) is reported as
  trace-unavailable rather than dropped (Req 12.5).
- `draft(request_id)` — a schema-conformant draft Golden_Item pre-filled
  with a unique `triage-{n}` id, the question text and detected language
  from the Trace, and `category: "TODO"`, `expected_source_ids: []`,
  `reference_answer: null` left for human annotation (Req 12.3). An
  unavailable Trace raises `TraceUnavailableError` and produces no draft
  (Req 12.6).

Dependencies are constructor-injected protocols so property tests (30–31)
run against in-memory fakes; `build_triage_service()` is the production
composition root, reusing `src.feedback.repository.DynamoFeedbackRepository`
and `src.observability.repository.DynamoTraceRepository` — no duplicate
data-access code.

CLI wiring (task 11.6): `backend/evals/cli.py` does not exist yet. When it
is built, it should route the `triage` subcommand to `run_triage(argv)`
below, i.e.::

    python -m evals triage list                  -> run_triage(["list"])
    python -m evals triage draft <request_id>    -> run_triage(["draft", rid])

`run_triage` handles argument parsing, output formatting, and exit codes,
so cli.py needs only the one-line dispatch.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from evals.dataset import DatasetLoader, GoldenDataset
from src.feedback.repository import DynamoFeedbackRepository, FeedbackRepository
from src.observability.repository import TraceRepository

DEFAULT_DATASET_PATH = Path(__file__).parent / "data" / "golden_dataset.jsonl"

# Arabic-script Unicode blocks: Arabic, Supplement, Extended-A, and the
# Presentation Forms. Used for query-language detection (design §triage).
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)

# A query is Arabic when at least half of its letters are Arabic-script.
_ARABIC_RATIO_THRESHOLD = 0.5


class TraceUnavailableError(Exception):
    """The Trace for the selected Feedback_Record does not exist in the
    Trace_Store, so no draft Golden_Item can be produced (Req 12.6)."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(
            f"trace unavailable for request {request_id!r}: never persisted "
            "(failed request) or expired past the retention period — no draft produced"
        )


@dataclass(frozen=True)
class TriageEntry:
    """One row of the triage listing (Req 12.2, 12.5).

    `query`/`response` come from the linked Trace; when the Trace does not
    exist, `trace_available` is False and both stay None.
    """

    request_id: str
    feedback_at: str
    trace_available: bool
    query: str | None = None
    response: str | None = None


@dataclass(frozen=True)
class GoldenItemDraft:
    """A draft Golden_Item conforming to the Golden_Dataset JSONL schema
    (Req 12.3): `id`, `question`, `language` pre-filled from the Trace;
    category, expected Source_IDs, and reference answer left for annotation.
    """

    id: str
    question: str
    language: str  # "ar" | "en", detected from the query text
    category: str = "TODO"
    expected_source_ids: tuple[str, ...] = field(default=())
    counterpart_id: None = None
    reference_answer: None = None

    def to_dict(self) -> dict:
        """The JSONL-schema dict, key-for-key like `GoldenItem.to_dict()`."""
        return {
            "id": self.id,
            "question": self.question,
            "language": self.language,
            "category": self.category,
            "expected_source_ids": list(self.expected_source_ids),
            "counterpart_id": self.counterpart_id,
            "reference_answer": self.reference_answer,
        }

    def to_jsonl(self) -> str:
        """One JSONL line, `ensure_ascii=False` so Arabic stays readable."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


def detect_language(text: str) -> str:
    """Detect "ar" vs "en" via the Arabic-script codepoint ratio.

    Counts letters only (punctuation, digits, and whitespace are neutral);
    Arabic wins when at least half the letters fall in an Arabic-script
    block. Text with no letters defaults to "en".
    """
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "en"
    arabic = sum(
        1
        for ch in letters
        if any(lo <= ord(ch) <= hi for lo, hi in _ARABIC_RANGES)
    )
    return "ar" if arabic / len(letters) >= _ARABIC_RATIO_THRESHOLD else "en"


class TriageService:
    """Feedback triage over injected repositories (design §triage.py).

    `feedback` and `traces` are the `src` protocols (production: the
    DynamoDB repositories; tests: in-memory fakes). `load_dataset` returns
    the current Golden_Dataset and is only invoked by `draft()`, which
    needs the existing item ids for uniqueness — the listing never touches
    the dataset.
    """

    def __init__(
        self,
        feedback: FeedbackRepository,
        traces: TraceRepository,
        load_dataset: Callable[[], GoldenDataset],
    ) -> None:
        self._feedback = feedback
        self._traces = traces
        self._load_dataset = load_dataset

    def list_down_rated(self) -> list[TriageEntry]:
        """Down-rated Feedback_Records newest-first, joined with their
        Traces (Req 12.2); missing Trace ⇒ trace-unavailable row (Req 12.5).

        Order comes from the repository (`RatingIndex` sort key descending),
        which this method preserves record-for-record. A genuine not-found
        (`get` returns None) becomes `trace_available=False`; transport
        failures (`TraceStoreError`) propagate — "no trace" and "could not
        check" stay distinguishable (Req 3.9).
        """
        entries: list[TriageEntry] = []
        for record in self._feedback.list_down_rated():
            trace = self._traces.get(record.request_id)
            if trace is None:
                entries.append(
                    TriageEntry(
                        request_id=record.request_id,
                        feedback_at=record.feedback_at,
                        trace_available=False,
                    )
                )
            else:
                entries.append(
                    TriageEntry(
                        request_id=record.request_id,
                        feedback_at=record.feedback_at,
                        trace_available=True,
                        query=trace.query,
                        response=trace.response,
                    )
                )
        return entries

    def draft(self, request_id: str) -> GoldenItemDraft:
        """Produce a draft Golden_Item for one triaged request (Req 12.3).

        Raises `TraceUnavailableError` (no draft) when the Trace does not
        exist (Req 12.6). Otherwise the draft carries the first free
        `triage-{n}` id (n = smallest positive integer whose id is not
        already taken in the existing dataset), the Trace's query as the
        question, and its detected language; category, expected Source_IDs,
        and reference answer stay TODO/[]/null for human annotation.
        """
        trace = self._traces.get(request_id)
        if trace is None:
            raise TraceUnavailableError(request_id)

        existing_ids = {item.id for item in self._load_dataset().items}
        n = 1
        while f"triage-{n}" in existing_ids:
            n += 1

        return GoldenItemDraft(
            id=f"triage-{n}",
            question=trace.query,
            language=detect_language(trace.query),
        )


# -- production wiring + CLI entry point (called by cli.py, task 11.6) --------


def build_triage_service(
    dataset_path: str | Path = DEFAULT_DATASET_PATH,
) -> TriageService:
    """Compose the production TriageService (design §triage.py).

    Reuses the existing single-gateway repositories: FEEDBACK_TABLE via
    `DynamoFeedbackRepository` and the shared `build_trace_repository()`
    composition root (TRACE_TABLE / TRACE_RETENTION_DAYS). Both are lazy,
    so construction needs no AWS credentials.
    """
    from src.observability.wiring import build_trace_repository

    return TriageService(
        feedback=DynamoFeedbackRepository(
            table_name=os.environ.get("FEEDBACK_TABLE", "noor-ai-feedback"),
        ),
        traces=build_trace_repository(),
        load_dataset=lambda: DatasetLoader().load(dataset_path),
    )


def run_triage(argv: Sequence[str], service: TriageService | None = None) -> int:
    """Execute `triage list` / `triage draft <request_id>`; returns exit code.

    This is the function cli.py (task 11.6) dispatches the `triage`
    subcommand to. `service` is injectable for tests; production callers
    omit it and get `build_triage_service()`.
    """
    if not argv or argv[0] not in {"list", "draft"}:
        print("usage: python -m evals triage list | draft <request_id>")
        return 2

    svc = service if service is not None else build_triage_service()

    if argv[0] == "list":
        entries = svc.list_down_rated()
        if not entries:
            print("no down-rated feedback records")
            return 0
        for entry in entries:
            if entry.trace_available:
                print(
                    f"{entry.request_id}  {entry.feedback_at}\n"
                    f"  query:    {entry.query}\n"
                    f"  response: {entry.response}"
                )
            else:
                print(
                    f"{entry.request_id}  {entry.feedback_at}\n"
                    "  trace unavailable (never persisted or expired)"
                )
        return 0

    # draft
    if len(argv) < 2:
        print("usage: python -m evals triage draft <request_id>")
        return 2
    try:
        print(svc.draft(argv[1]).to_jsonl())
    except TraceUnavailableError as exc:
        print(f"error: {exc}")
        return 1
    return 0
