"""Property 13: Golden dataset JSONL round trip (design.md Correctness Properties).

*For any* valid Golden_Dataset (Arabic and English questions, optional
reference answers), serializing to UTF-8 JSONL and loading back yields an
equivalent set of Golden_Items.

**Validates: Requirements 4.1, 4.5**

Pure filesystem-tmp Hypothesis test — no AWS calls. The composite strategy
generates structurally valid datasets satisfying every count constraint
(50–100 items, ≥20 per language, ≥5 per category), with linked cross-lingual
pairs, out_of_corpus items with empty expected ids, items with and without
reference answers, and Arabic/English question text. Files are written with
``tempfile`` inside the test body because Hypothesis and the function-scoped
pytest ``tmp_path`` fixture interact poorly (fixture is created once per
test function, not per generated example).
"""
import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import DatasetLoader

# -- field strategies ---------------------------------------------------------

# Question text per language: Arabic script for "ar", printable ASCII for
# "en", both salted with punctuation/emoji so escaping is exercised.
arabic_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
        st.sampled_from(" ؟،🕌📖"),
    ),
    min_size=1,
    max_size=60,
)
english_text = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
    min_size=1,
    max_size=60,
)

# Reference answers: sometimes authored (in either script, including quotes
# and backslashes that stress JSON escaping), sometimes absent (Req 4.5).
reference_answers = st.none() | st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),
        st.sampled_from('"\\\n\t🕌'),
    ),
    min_size=1,
    max_size=120,
)

# Expected Source_IDs conforming to the corpus citation grammar.
source_ids = st.one_of(
    st.tuples(st.integers(1, 114), st.integers(1, 286)).map(
        lambda t: f"Quran {t[0]}:{t[1]}"
    ),
    st.integers(1, 7563).map(lambda n: f"Sahih al-Bukhari {n}"),
    st.integers(1, 3033).map(lambda n: f"Sahih Muslim {n}"),
)
source_id_lists = st.lists(source_ids, min_size=1, max_size=3, unique=True)

# Unicode salt appended to deterministic id bases ('#' never appears in a
# base and all bases are distinct, so uniqueness is preserved).
id_suffixes = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E, exclude_characters="#"),
    max_size=8,
)

QUESTIONS = {"ar": arabic_text, "en": english_text}


@st.composite
def golden_dataset_dicts(draw) -> list[dict]:
    """A structurally valid Golden_Dataset as a list of raw item dicts.

    Satisfies all dataset-level constraints: per-language totals ≥ 25 (so
    the grand total lands in 50–54 ⊂ [50, 100]), ≥ 20 per language, ≥ 5
    per category, linked cross-lingual pairs sharing Source_ID sets,
    out_of_corpus items with empty expected ids, and unique item ids.
    Optional fields (counterpart_id, reference_answer) are randomly either
    present or omitted from the serialized JSON object.
    """
    items: list[dict] = []

    def build(base_id: str, lang: str, category: str, expected: list[str], counterpart: str | None = None) -> dict:
        item = {
            "id": f"{base_id}#{draw(id_suffixes)}",
            "question": draw(QUESTIONS[lang]),
            "language": lang,
            "category": category,
            "expected_source_ids": expected,
        }
        # Optional keys: present-with-value, present-as-null, or omitted.
        if counterpart is not None:
            item["counterpart_id"] = counterpart
        elif draw(st.booleans()):
            item["counterpart_id"] = None
        reference = draw(reference_answers)
        if reference is not None or draw(st.booleans()):
            item["reference_answer"] = reference
        return item

    pairs = draw(st.integers(min_value=3, max_value=5))
    for lang in ("ar", "en"):
        direct = draw(st.integers(min_value=3, max_value=10))
        para = draw(st.integers(min_value=3, max_value=6))
        ooc = draw(st.integers(min_value=3, max_value=6))
        # Pad direct_lookup so each language reaches ≥ 25 items.
        direct += max(0, 25 - (direct + para + ooc + pairs))
        for n in range(direct):
            items.append(
                build(f"{lang}-direct-{n:03d}", lang, "direct_lookup", draw(source_id_lists))
            )
        for n in range(para):
            items.append(
                build(f"{lang}-para-{n:03d}", lang, "paraphrase", draw(source_id_lists))
            )
        for n in range(ooc):
            items.append(build(f"{lang}-ooc-{n:03d}", lang, "out_of_corpus", []))

    for n in range(pairs):
        shared = draw(source_id_lists)
        ar = build(
            f"ar-cross-{n:03d}", "ar", "cross_lingual", list(shared),
            counterpart=None,  # patched below once both ids exist
        )
        en = build(f"en-cross-{n:03d}", "en", "cross_lingual", list(shared))
        ar["counterpart_id"] = en["id"]
        en["counterpart_id"] = ar["id"]
        items.extend((ar, en))

    # Shuffle so round-trip order preservation is not an artifact of the
    # generation order.
    return draw(st.permutations(items))


def serialize_jsonl(items: list[dict]) -> bytes:
    """UTF-8 JSONL: exactly one JSON object per line (Req 4.1)."""
    return (
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n"
    ).encode("utf-8")


class TestProperty13GoldenDatasetJsonlRoundTrip:
    # deadline=None: each example writes real files; filesystem latency
    # jitter must not fail otherwise-passing examples.
    @settings(max_examples=100, deadline=None)
    @given(items=golden_dataset_dicts())
    def test_serialize_then_load_yields_identical_items_in_order(self, items):
        """Serializing valid Golden_Items to UTF-8 JSONL and loading via
        DatasetLoader yields items with identical field values in the same
        order (Req 4.1, 4.5)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "golden_dataset.jsonl"
            path.write_bytes(serialize_jsonl(items))
            path.with_suffix(".meta.json").write_text(
                json.dumps({"version": "1.0.0"}), encoding="utf-8"
            )

            dataset = DatasetLoader().load(path)

        assert len(dataset.items) == len(items)
        for loaded, original in zip(dataset.items, items):
            assert loaded.id == original["id"]
            assert loaded.question == original["question"]
            assert loaded.language == original["language"]
            assert loaded.category == original["category"]
            assert loaded.expected_source_ids == tuple(original["expected_source_ids"])
            # Omitted optional keys round-trip as None.
            assert loaded.counterpart_id == original.get("counterpart_id")
            assert loaded.reference_answer == original.get("reference_answer")
