"""Property 22: Rubric selection by category (design.md Correctness Properties).

*For any* Golden_Item, generation scoring applies exactly the single
abstention rubric when the item's category is out_of_corpus, and exactly the
faithfulness, citation-accuracy, and answer-relevancy rubrics otherwise.

**Validates: Requirements 8.4**

Pure in-memory Hypothesis test — no AWS calls. `GenerationScorer` is driven
with a scripted `Judge` fake that records every rubric it is asked to score,
so the property is checked on both sides of the boundary: the rubrics the
judge actually receives, and the rubric names carried by the resulting
`ItemGenerationScores.outcomes`.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import GoldenItem
from evals.judge import RetrievedChunk, Rubric, Verdict
from evals.metrics.generation import GenerationScorer, rubrics_for

STANDARD_RUBRIC_NAMES = ("faithfulness", "citation_accuracy", "answer_relevancy")
ABSTENTION_RUBRIC_NAMES = ("abstention",)

# -- strategies ----------------------------------------------------------------

# Free text in both scripts (questions, answers, chunk contents).
any_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
    ),
    min_size=1,
    max_size=80,
)

# Expected Source_IDs conforming to the corpus citation grammar.
source_ids = st.one_of(
    st.tuples(st.integers(1, 114), st.integers(1, 286)).map(
        lambda t: f"Quran {t[0]}:{t[1]}"
    ),
    st.integers(1, 7563).map(lambda n: f"Sahih al-Bukhari {n}"),
    st.integers(1, 3033).map(lambda n: f"Sahih Muslim {n}"),
)


@st.composite
def golden_items(draw) -> GoldenItem:
    """A Golden_Item of any category, built directly (no file I/O).

    Category-consistent fields mirror the dataset invariants: out_of_corpus
    items carry no expected Source_IDs, every other category carries at
    least one; cross_lingual items carry a counterpart_id.
    """
    category = draw(
        st.sampled_from(
            ["direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus"]
        )
    )
    if category == "out_of_corpus":
        expected: tuple[str, ...] = ()
    else:
        expected = tuple(draw(st.lists(source_ids, min_size=1, max_size=3, unique=True)))
    return GoldenItem(
        id=draw(st.uuids()).hex,
        question=draw(any_text),
        language=draw(st.sampled_from(["ar", "en"])),
        category=category,
        expected_source_ids=expected,
        counterpart_id=draw(st.uuids()).hex if category == "cross_lingual" else None,
        reference_answer=draw(st.none() | any_text),
    )


retrieved_chunks = st.lists(
    st.builds(RetrievedChunk, source_id=source_ids, text=any_text),
    max_size=4,
).map(tuple)


class RecordingJudge:
    """Scripted `Judge` fake: records every rubric it is asked to score."""

    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = verdicts  # cycled per call
        self.rubrics_seen: list[Rubric] = []
        self.calls: list[tuple[str, str]] = []  # (rubric name, item id)

    def score(self, rubric, item, answer, retrieved) -> Verdict:
        self.rubrics_seen.append(rubric)
        self.calls.append((rubric.name, item.id))
        verdict = self._verdicts[(len(self.calls) - 1) % len(self._verdicts)]
        return Verdict(verdict=verdict, rationale=f"scripted {rubric.name}")


def expected_rubric_names(item: GoldenItem) -> tuple[str, ...]:
    """The rubric names Property 22 mandates for `item`'s category."""
    if item.category == "out_of_corpus":
        return ABSTENTION_RUBRIC_NAMES
    return STANDARD_RUBRIC_NAMES


class TestProperty22RubricSelectionByCategory:
    @settings(max_examples=100)
    @given(
        item=golden_items(),
        answer=any_text,
        retrieved=retrieved_chunks,
        verdicts=st.lists(st.sampled_from(["pass", "fail"]), min_size=1, max_size=3),
    )
    def test_judge_receives_exactly_the_category_rubrics(
        self, item, answer, retrieved, verdicts
    ):
        """For any item, answer, and retrieved chunks, the judge is called
        with exactly the abstention rubric for out_of_corpus items and
        exactly faithfulness + citation_accuracy + answer_relevancy for
        every other category — no more, no fewer, no duplicates (Req 8.4)."""
        judge = RecordingJudge(verdicts)
        scorer = GenerationScorer(judge)

        result = scorer.score_item(item, answer, retrieved)

        expected = expected_rubric_names(item)
        # The judge saw exactly the mandated rubrics, once each.
        assert tuple(name for name, _ in judge.calls) == expected
        assert all(item_id == item.id for _, item_id in judge.calls)
        # The resulting Generation_Metrics carry exactly those rubric names.
        assert result.computed is True
        assert tuple(outcome.rubric for outcome in result.outcomes) == expected

    @settings(max_examples=100)
    @given(item=golden_items())
    def test_rubrics_for_selects_by_category(self, item):
        """`rubrics_for` itself returns exactly the mandated rubric set for
        any Golden_Item's category (Req 8.4)."""
        names = tuple(rubric.name for rubric in rubrics_for(item))
        assert names == expected_rubric_names(item)

    @settings(max_examples=100)
    @given(
        item=golden_items(),
        answer=any_text,
        retrieved=retrieved_chunks,
    )
    def test_outcomes_reflect_scripted_verdicts_for_selected_rubrics(
        self, item, answer, retrieved
    ):
        """Each outcome pairs the selected rubric with the judge's verdict —
        rubric selection never alters or reorders verdicts (Req 8.4)."""
        judge = RecordingJudge(["pass"])
        scorer = GenerationScorer(judge)

        result = scorer.score_item(item, answer, retrieved)

        assert len(result.outcomes) == len(expected_rubric_names(item))
        for outcome, seen in zip(result.outcomes, judge.rubrics_seen):
            assert outcome.rubric == seen.name
            assert outcome.outcome == "pass"
