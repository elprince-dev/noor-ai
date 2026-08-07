"""Property 15: Version identifier sensitivity (design.md Correctness Properties).

*For any* two Golden_Dataset states, their version identifiers are equal if
and only if their content is identical — so any addition (including a triaged
item), removal, or edit of a Golden_Item produces a different identifier.

**Validates: Requirements 5.1, 12.4**

Pure filesystem-tmp Hypothesis test — no AWS calls. Reuses the valid-dataset
strategy from the round-trip property test, padded with one extra
direct_lookup item per language so that a removal mutation always leaves the
dataset within every count constraint (total ≥ 50, ≥ 20 per language, ≥ 5 per
category). Each example generates a valid dataset, applies one random
content-changing mutation (edit a question, add an item, remove an item, or
reorder with a content change), loads both states through `DatasetLoader`,
and asserts the effective version identifiers differ. A companion test
asserts the identity direction: byte-identical content yields the identical
version regardless of file location. Files are written with ``tempfile``
inside the test body because Hypothesis and the function-scoped pytest
``tmp_path`` fixture interact poorly.
"""
import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import DatasetLoader
from tests.evals.test_property_dataset_roundtrip import (
    QUESTIONS,
    golden_dataset_dicts,
    serialize_jsonl,
    source_id_lists,
)

MUTATION_KINDS = ("edit_question", "add_item", "remove_item", "reorder_with_edit")

# Suffix appended to a question when editing it: always non-empty, so the
# item's content — and therefore the serialized bytes — is guaranteed to
# change. Question fields only require a non-empty string, so any printable
# suffix keeps the item valid.
question_suffixes = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x21, max_codepoint=0x7E),
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),
    ),
    min_size=1,
    max_size=10,
)


@st.composite
def padded_dataset_dicts(draw) -> list[dict]:
    """A valid Golden_Dataset with one extra direct_lookup item per language.

    The padding keeps every removal mutation safely inside the dataset-level
    count constraints: per-language totals ≥ 26 (removal → ≥ 25 ≥ 20), grand
    total ≥ 52 (removal → ≥ 51, and ≤ 56 so an addition stays ≤ 100), and
    direct_lookup ≥ 8 (removal → ≥ 7 ≥ 5). Padded ids contain no '#' while
    every base-strategy id does, so uniqueness is preserved.
    """
    items = list(draw(golden_dataset_dicts()))
    for lang in ("ar", "en"):
        items.append(
            {
                "id": f"pad-{lang}-direct",
                "question": draw(QUESTIONS[lang]),
                "language": lang,
                "category": "direct_lookup",
                "expected_source_ids": draw(source_id_lists),
            }
        )
    return items


def apply_mutation(items: list[dict], kind: str, data: st.DataObject) -> list[dict]:
    """Return a mutated deep-enough copy of `items` that stays valid.

    Every mutation changes the item set or the content of an item, so per
    Property 15 the resulting version identifier must differ.
    """
    mutated = [dict(item) for item in items]

    def edit_question(target: list[dict]) -> None:
        idx = data.draw(st.integers(0, len(target) - 1), label="edited item index")
        suffix = data.draw(question_suffixes, label="question suffix")
        target[idx]["question"] = target[idx]["question"] + suffix

    if kind == "edit_question":
        edit_question(mutated)
    elif kind == "add_item":
        # A triaged item entering the dataset (Req 12.4): valid direct_lookup
        # item whose id ('#'-free, distinct from the two pad ids) is unique.
        lang = data.draw(st.sampled_from(["ar", "en"]), label="added item language")
        mutated.append(
            {
                "id": "triage-added-item",
                "question": data.draw(QUESTIONS[lang], label="added item question"),
                "language": lang,
                "category": "direct_lookup",
                "expected_source_ids": data.draw(source_id_lists, label="added item source ids"),
            }
        )
    elif kind == "remove_item":
        # Never remove a cross_lingual item — that would dangle its
        # counterpart reference and make the mutated dataset unloadable.
        removable = [
            i for i, item in enumerate(mutated) if item["category"] != "cross_lingual"
        ]
        idx = data.draw(st.sampled_from(removable), label="removed item index")
        del mutated[idx]
    elif kind == "reorder_with_edit":
        mutated = list(data.draw(st.permutations(mutated), label="reordered items"))
        edit_question(mutated)
    else:  # pragma: no cover - guarded by MUTATION_KINDS
        raise AssertionError(f"unknown mutation kind {kind!r}")

    return mutated


def load_version(jsonl_bytes: bytes, directory: Path) -> str:
    """Write a dataset + manifest into `directory` and return its version."""
    path = directory / "golden_dataset.jsonl"
    path.write_bytes(jsonl_bytes)
    path.with_suffix(".meta.json").write_text(
        json.dumps({"version": "1.0.0"}), encoding="utf-8"
    )
    return DatasetLoader().load(path).version


class TestProperty15VersionIdentifierSensitivity:
    # deadline=None: each example writes real files; filesystem latency
    # jitter must not fail otherwise-passing examples.
    @settings(max_examples=100, deadline=None)
    @given(
        items=padded_dataset_dicts(),
        kind=st.sampled_from(MUTATION_KINDS),
        data=st.data(),
    )
    def test_any_content_change_produces_a_different_version(self, items, kind, data):
        """Editing a question, adding an item (e.g. from triage), removing an
        item, or reordering with a content change all yield a version
        identifier different from the pre-mutation identifier (Req 5.1, 12.4).
        """
        mutated = apply_mutation(items, kind, data)

        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            version_before = load_version(serialize_jsonl(items), Path(dir_a))
            version_after = load_version(serialize_jsonl(mutated), Path(dir_b))

        assert version_before != version_after, (
            f"mutation {kind!r} changed dataset content but the version "
            f"identifier stayed {version_before!r}"
        )

    @settings(max_examples=100, deadline=None)
    @given(items=padded_dataset_dicts())
    def test_identical_content_yields_identical_version(self, items):
        """The same dataset bytes loaded from two different locations produce
        the identical version identifier — the version is a pure function of
        the manifest label and content (Req 5.1)."""
        jsonl_bytes = serialize_jsonl(items)

        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            version_a = load_version(jsonl_bytes, Path(dir_a))
            version_b = load_version(jsonl_bytes, Path(dir_b))

        assert version_a == version_b
        assert version_a.startswith("1.0.0+")
