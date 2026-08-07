"""Property 16: Runner executes every item independently and records results
faithfully (design.md Correctness Properties).

*For any* valid Golden_Dataset run against a mocked pipeline, every
Golden_Item is executed exactly once with no conversation state shared
between items, and each per-item result records together the item ID, the
retrieved Source_IDs with scores, and the generated answer exactly as
produced.

**Validates: Requirements 6.1, 6.3**

Pure in-memory Hypothesis test — no AWS calls, no filesystem. The strategy
generates small Golden_Datasets (GoldenDataset is constructed directly from
GoldenItems; the count validation lives in DatasetLoader, not the dataclass)
together with a scripted retrieval output and generated answer per item. The
fakes record every call so the test can assert:

(a) independence — retrieval and generation are each called exactly once per
    item, each call carries only that item's own question, and the generation
    context is exactly that item's scripted context (no carryover from
    previous items);
(b) per-item fidelity — each result records the item ID, the exact retrieved
    Source_IDs with scores in rank order, and the generated answer together;
(c) report fidelity — the persisted report's per_item entries match the
    scripted outputs and counts.succeeded/failed are correct.
"""
from dataclasses import asdict

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

# Question/answer text spanning ASCII and Arabic script (with JSON-hostile
# characters) so recording fidelity is exercised on realistic content.
text_content = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),
        st.sampled_from('"\\\n\t؟🕌'),
    ),
    min_size=1,
    max_size=60,
)

# Expected Source_IDs conforming to the corpus citation grammar.
expected_source_ids = st.one_of(
    st.tuples(st.integers(1, 114), st.integers(1, 286)).map(
        lambda t: f"Quran {t[0]}:{t[1]}"
    ),
    st.integers(1, 7563).map(lambda n: f"Sahih al-Bukhari {n}"),
    st.integers(1, 3033).map(lambda n: f"Sahih Muslim {n}"),
)

# Retrieved Source_IDs are recorded verbatim — any non-empty string.
retrieved_source_id = st.text(min_size=1, max_size=30)

# Scores round-trip through float() in the runner; exclude NaN (breaks
# equality) and infinities (not meaningful relevance scores).
scores = st.floats(allow_nan=False, allow_infinity=False, width=32)

# One scripted retrieval output: ranked (Source_ID, score) pairs with
# aligned chunk texts, plus the formatted context block. Zero results is a
# legal retrieval outcome and must still be recorded faithfully.
scripted_retrievals = st.lists(
    st.tuples(retrieved_source_id, scores, text_content), min_size=0, max_size=4
).map(
    lambda entries: RetrievalResult(
        sources=[(sid, score) for sid, score, _ in entries],
        context="\n".join(f"[{sid}] {text}" for sid, _, text in entries),
        texts=tuple(text for _, _, text in entries),
    )
)


@st.composite
def datasets_with_scripts(draw):
    """A small valid GoldenDataset plus scripted per-item pipeline outputs.

    Returns (dataset, retrieval_by_question, answer_by_question). Questions
    are made unique by embedding each item's unique id, so the fakes can key
    their scripts by question and detect any cross-item call mixing.
    """
    n = draw(st.integers(min_value=1, max_value=8))
    items: list[GoldenItem] = []
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
                draw(st.lists(expected_source_ids, min_size=1, max_size=3, unique=True))
            )
        )
        items.append(
            GoldenItem(
                id=item_id,
                question=question,
                language=draw(st.sampled_from(("ar", "en"))),
                category=category,
                expected_source_ids=expected,
                # counterpart links are loader-validation concerns, not
                # runner concerns; cross_lingual items still need one set.
                counterpart_id="peer" if category == "cross_lingual" else None,
            )
        )
        retrieval_by_question[question] = draw(scripted_retrievals)
        answer_by_question[question] = draw(text_content)

    dataset = GoldenDataset(items=tuple(items), version="1.0.0+deadbeef1234")
    return dataset, retrieval_by_question, answer_by_question


eval_configs = st.builds(
    EvalConfig,
    model_id=st.just("us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    retrieval_top_k=st.integers(min_value=1, max_value=10),
    prompt_version=st.sampled_from(("v1", "v2")),
    judge_model_id=st.just("amazon.nova-pro-v1:0"),
)


# -- in-memory fakes (no AWS) --------------------------------------------------


class ScriptedRetrievalClient:
    """Returns the scripted RetrievalResult for each question; records calls."""

    def __init__(self, script: dict[str, RetrievalResult]) -> None:
        self._script = script
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, question: str, top_k: int) -> RetrievalResult:
        self.calls.append((question, top_k))
        # A question outside the script means the runner leaked or mutated
        # state between items — fail loudly (independence, Req 6.1).
        assert question in self._script, f"unexpected retrieval question {question!r}"
        return self._script[question]


class ScriptedGenerationClient:
    """Returns the scripted answer for each question; records calls."""

    def __init__(self, script: dict[str, str]) -> None:
        self._script = script
        self.calls: list[tuple[str, str, str]] = []  # (question, context, version)

    def generate(self, question: str, context: str, prompt_version: str) -> str:
        self.calls.append((question, context, prompt_version))
        assert question in self._script, f"unexpected generation question {question!r}"
        return self._script[question]


class ScriptedScorer:
    """GenerationScorerLike fake: one deterministic computed score per item."""

    def __init__(self) -> None:
        self.score_calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []

    def score_item(self, item, answer, retrieved) -> ItemGenerationScores:
        self.score_calls.append(
            (item.id, answer, tuple((c.source_id, c.text) for c in retrieved))
        )
        return ItemGenerationScores(
            item_id=item.id,
            category=item.category,
            language=item.language,
            computed=True,
            outcomes=(RubricOutcome(rubric="faithfulness", outcome="pass", rationale="ok"),),
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


class TestProperty16RunnerIndependenceAndFidelity:
    @settings(max_examples=100)
    @given(data=datasets_with_scripts(), config=eval_configs)
    def test_every_item_executed_once_independently_and_recorded_faithfully(
        self, data, config
    ):
        dataset, retrieval_script, answer_script = data
        # Fresh fakes per example: any call recorded here belongs to this run.
        retrieval = ScriptedRetrievalClient(retrieval_script)
        generator = ScriptedGenerationClient(answer_script)
        scorer = ScriptedScorer()
        reports = RecordingReports()

        report = EvalRunner(retrieval, generator, scorer, reports).run(config, dataset)

        questions = [item.question for item in dataset.items]

        # (a) Independence (Req 6.1): every item goes through retrieval and
        # generation exactly once, in dataset order, each call carrying only
        # its own question — no duplicates, no omissions, no cross-item state.
        assert [q for q, _ in retrieval.calls] == questions
        assert all(top_k == config.retrieval_top_k for _, top_k in retrieval.calls)

        assert [q for q, _, _ in generator.calls] == questions
        for item, (question, context, prompt_version) in zip(
            dataset.items, generator.calls
        ):
            assert question == item.question
            # Context is exactly this item's scripted context: nothing from
            # any other item's retrieval leaked into this generation call.
            assert context == retrieval_script[item.question].context
            assert prompt_version == config.prompt_version

        # The scorer sees each item exactly once, with that item's answer and
        # its own retrieved chunks (Source_ID + text pairs, in rank order).
        assert [item_id for item_id, _, _ in scorer.score_calls] == [
            item.id for item in dataset.items
        ]
        for item, (_, answer, chunks) in zip(dataset.items, scorer.score_calls):
            scripted = retrieval_script[item.question]
            assert answer == answer_script[item.question]
            assert chunks == tuple(
                (sid, text) for (sid, _), text in zip(scripted.sources, scripted.texts)
            )

        # (b, c) Fidelity (Req 6.3): each per-item report entry records the
        # item ID, the exact retrieved Source_IDs with scores in rank order,
        # and the generated answer together, exactly as scripted.
        assert len(report["per_item"]) == len(dataset.items)
        for item, entry in zip(dataset.items, report["per_item"]):
            scripted = retrieval_script[item.question]
            assert entry["item_id"] == item.id
            assert entry["retrieved"] == [
                [sid, float(score)] for sid, score in scripted.sources
            ]
            assert entry["answer"] == answer_script[item.question]
            assert entry["failed"] is False
            assert entry["failing_step"] is None
            assert entry["error"] is None

        # Counts are correct: everything succeeded, nothing failed.
        assert report["counts"] == {
            "succeeded": len(dataset.items),
            "failed": 0,
        }

        # The persisted report is exactly the returned report — persisted
        # once, with the config and dataset version carried faithfully.
        assert reports.persisted == [report]
        assert report["config"] == asdict(config)
        assert report["dataset_version"] == dataset.version
