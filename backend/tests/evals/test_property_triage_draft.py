"""Property 31: Draft Golden_Item generation (design.md Correctness Properties).

*For any* persisted Trace (Arabic or English query) and existing
Golden_Dataset, the triage draft is a schema-conformant Golden_Item with an
item ID unique across the dataset, the question text and detected language
taken from the Trace, and the category, expected Source_IDs, and reference
answer left for human annotation; and requesting a draft for a Request_ID
whose Trace is unavailable fails with a trace-unavailable error and produces
no draft.

**Validates: Requirements 12.3, 12.6**

Pure in-memory Hypothesis test — no AWS calls. The trace repository and the
dataset loader are constructor-injected fakes. Query text is generated with
a known letter composition (Arabic-script vs Latin letters plus neutral
characters), so the expected language is an independent oracle: "ar" when at
least half the letters are Arabic-script, "en" otherwise — the exact
detection rule from the design (§triage.py).
"""
import json
import re

from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import GoldenDataset, GoldenItem
from evals.triage import TraceUnavailableError, TriageService
from src.observability.models import CostEstimate, Trace

TRIAGE_ID_PATTERN = re.compile(r"^triage-[1-9]\d*$")

# The exact key set of the Golden_Dataset JSONL schema (GoldenItem.to_dict).
GOLDEN_ITEM_KEYS = {
    "id",
    "question",
    "language",
    "category",
    "expected_source_ids",
    "counterpart_id",
    "reference_answer",
}


# -- fakes ---------------------------------------------------------------------


class FakeFeedbackRepository:
    """Draft never touches feedback; present only to satisfy the constructor."""

    def list_down_rated(self):
        return []


class FakeTraceRepository:
    """Dict-backed TraceRepository: `get` returns the Trace or None."""

    def __init__(self, traces: dict[str, Trace]):
        self._traces = traces

    def get(self, request_id: str) -> Trace | None:
        return self._traces.get(request_id)


def make_trace(request_id: str, query: str) -> Trace:
    """A minimal but complete persisted Trace carrying `query`."""
    return Trace(
        request_id=request_id,
        session_id="session-1",
        received_at="2024-01-01T00:00:00+00:00",
        query=query,
        model_id="anthropic.claude-haiku-4-5",
        retrieval=(),
        final_prompt="prompt",
        response="answer",
        input_tokens=10,
        output_tokens=20,
        cost=CostEstimate(computed=False, reason="test"),
        ttft_ms=100,
        total_latency_ms=500,
    )


def make_dataset(ids: set[str]) -> GoldenDataset:
    """A GoldenDataset whose items carry exactly `ids` (content irrelevant
    to drafting — only the id set matters for uniqueness)."""
    items = tuple(
        GoldenItem(
            id=item_id,
            question="q",
            language="en",
            category="direct_lookup",
            expected_source_ids=("Quran 1:1",),
        )
        for item_id in sorted(ids)
    )
    return GoldenDataset(items=items, version="1.0.0+000000000000")


# -- strategies ----------------------------------------------------------------

# Letters only (filtered by isalpha so the oracle's letter count is exact):
# Arabic block 0x0621–0x064A for Arabic script, ASCII for Latin.
arabic_letters = st.characters(min_codepoint=0x0621, max_codepoint=0x064A).filter(
    str.isalpha
)
latin_letters = st.characters(
    min_codepoint=0x41, max_codepoint=0x7A
).filter(str.isalpha)

# Neutral characters: not letters, so they never shift the detection ratio.
neutral_chars = st.sampled_from(" ؟،?.!,:0123456789٣")


@st.composite
def queries_with_expected_language(draw) -> tuple[str, str]:
    """A query with ≥1 letter and its independently-derived language.

    Composition is drawn explicitly (Arabic letter count vs Latin letter
    count), so the expected language follows from the design's rule without
    consulting the implementation: "ar" iff arabic / letters >= 0.5.
    """
    arabic = draw(st.lists(arabic_letters, min_size=0, max_size=30))
    latin = draw(st.lists(latin_letters, min_size=0, max_size=30))
    if not arabic and not latin:
        arabic = [draw(arabic_letters)]
    neutral = draw(st.lists(neutral_chars, min_size=0, max_size=15))
    chars = draw(st.permutations(arabic + latin + neutral))
    expected = "ar" if len(arabic) / (len(arabic) + len(latin)) >= 0.5 else "en"
    return "".join(chars), expected


# Existing dataset ids: a mix of ordinary ids and contended `triage-{n}` ids
# so the uniqueness search is actually exercised (including gaps).
ordinary_ids = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=1,
    max_size=12,
).filter(lambda s: not TRIAGE_ID_PATTERN.match(s))
triage_ids = st.integers(min_value=1, max_value=8).map(lambda n: f"triage-{n}")
existing_id_sets = st.sets(st.one_of(ordinary_ids, triage_ids), min_size=0, max_size=12)

request_ids = st.uuids().map(str)


# -- tests ---------------------------------------------------------------------


class TestProperty31DraftGoldenItemGeneration:
    @settings(max_examples=100)
    @given(
        query_and_lang=queries_with_expected_language(),
        existing_ids=existing_id_sets,
        request_id=request_ids,
    )
    def test_draft_is_schema_conformant_with_trace_fields_and_unique_id(
        self, query_and_lang, existing_ids, request_id
    ):
        """For any persisted Trace and existing dataset, the draft carries
        the exact question text, the language per the Arabic-script ratio
        rule, an id unique against the dataset, empty expected Source_IDs,
        and the annotation placeholders; its JSONL line parses as a single
        JSON object (Req 12.3)."""
        query, expected_language = query_and_lang
        service = TriageService(
            feedback=FakeFeedbackRepository(),
            traces=FakeTraceRepository({request_id: make_trace(request_id, query)}),
            load_dataset=lambda: make_dataset(existing_ids),
        )

        draft = service.draft(request_id)

        # Question text and detected language come from the Trace (Req 12.3).
        assert draft.question == query
        assert draft.language == expected_language

        # Unique `triage-{n}` id against the existing dataset ids.
        assert TRIAGE_ID_PATTERN.match(draft.id)
        assert draft.id not in existing_ids

        # Annotation placeholders left for the human (Req 12.3).
        assert draft.category == "TODO"
        assert draft.expected_source_ids == ()
        assert draft.counterpart_id is None
        assert draft.reference_answer is None

        # JSONL conformance: exactly one line parsing as one JSON object
        # with exactly the Golden_Dataset schema keys.
        line = draft.to_jsonl()
        assert "\n" not in line
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        assert set(parsed.keys()) == GOLDEN_ITEM_KEYS
        assert parsed["id"] == draft.id
        assert parsed["question"] == query
        assert parsed["language"] == expected_language
        assert parsed["category"] == "TODO"
        assert parsed["expected_source_ids"] == []
        assert parsed["counterpart_id"] is None
        assert parsed["reference_answer"] is None

    @settings(max_examples=100)
    @given(
        existing_ids=existing_id_sets,
        request_id=request_ids,
        other_traces=st.dictionaries(
            st.uuids().map(str),
            st.text(min_size=1, max_size=20),
            max_size=3,
        ),
    )
    def test_unavailable_trace_raises_and_produces_no_draft(
        self, existing_ids, request_id, other_traces
    ):
        """Requesting a draft for a Request_ID whose Trace does not exist
        raises TraceUnavailableError naming the id — no draft (Req 12.6)."""
        traces = {
            rid: make_trace(rid, q)
            for rid, q in other_traces.items()
            if rid != request_id
        }
        dataset_loads = []

        def load_dataset():
            dataset_loads.append(True)
            return make_dataset(existing_ids)

        service = TriageService(
            feedback=FakeFeedbackRepository(),
            traces=FakeTraceRepository(traces),
            load_dataset=load_dataset,
        )

        try:
            service.draft(request_id)
        except TraceUnavailableError as exc:
            assert exc.request_id == request_id
            assert request_id in str(exc)
        else:
            raise AssertionError("expected TraceUnavailableError, got a draft")

        # No draft was produced: the dataset was never even consulted.
        assert dataset_loads == []
