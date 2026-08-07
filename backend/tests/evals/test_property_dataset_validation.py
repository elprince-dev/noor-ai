"""Property 14: Dataset validation accepts the valid and rejects the invalid
with location (design.md Correctness Properties).

*For any* generated valid Golden_Dataset, loading succeeds; and *for any*
valid dataset corrupted by a random violation (missing/duplicate id, empty
question, illegal language or category, malformed Source_ID,
category-inconsistent expected ids, dangling/same-language/mismatched
cross-lingual counterpart, or count constraints out of range), loading
rejects the entire file and reports the offending line number and the
specific check that failed.

**Validates: Requirements 4.2, 4.3, 4.4, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11**

Pure filesystem-tmp Hypothesis test — no AWS calls. Valid datasets come from
the shared ``golden_dataset_dicts`` strategy (Property 13 module); each
corrupted example injects exactly one randomly chosen fault into a valid
dataset and asserts the resulting ``DatasetValidationError`` carries a
finding with the injected fault's line number and check name. Files are
written with ``tempfile`` inside the test body because Hypothesis and the
function-scoped pytest ``tmp_path`` fixture interact poorly.
"""
import copy
import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.dataset import DatasetLoader, DatasetValidationError
from tests.evals.test_property_dataset_roundtrip import golden_dataset_dicts

# -- fault ingredients --------------------------------------------------------

# Lines that either fail JSON parsing or parse to a non-object (both are the
# "json_parse" check). None are blank, so the loader will not skip them.
GARBAGE_LINES = (
    "{",
    "not json at all",
    "[1, 2",
    '{"id": }',
    '"just a string"',
    "[1, 2, 3]",
    "42",
)

INVALID_LANGUAGES = ("fr", "AR", "EN", "arabic", "english", "ar-SA")
INVALID_CATEGORIES = ("lookup", "Direct_Lookup", "ooc", "crosslingual", "misc")

# Strings violating the Source_ID grammar (Req 4.9 / Glossary).
MALFORMED_SOURCE_IDS = (
    "Quran 1",
    "quran 1:1",
    "Quran 1:2:3",
    " Quran 1:1",
    "Sahih Bukhari 5",
    "Sahih al-Bukhari",
    "Sahih al-Tirmidhi 12",
    "Bukhari 99",
)

# Valid per the grammar but impossible for golden_dataset_dicts to generate
# (surah numbers stop at 114), so appending it always changes an ID set.
FOREIGN_SOURCE_ID = "Quran 99999:99999"

# An id that golden_dataset_dicts can never produce (bases never start with
# '#', suffixes exclude '#').
NONEXISTENT_ID = "##no-such-item##"

REQUIRED_FIELDS = ("id", "question", "language", "category", "expected_source_ids")


def _pick_index(draw, items: list[dict], predicate) -> int:
    """Index of a random item satisfying `predicate` (generator guarantees
    every category/language combination this module targets is populated)."""
    candidates = [i for i, item in enumerate(items) if predicate(item)]
    return draw(st.sampled_from(candidates))


# -- fault injectors ----------------------------------------------------------
# Each injector mutates `items` (and/or replaces a serialized line later via
# the returned garbage marker) and returns (expected_line, expected_check).
# Line numbers are 1-based; dataset-level findings use line 0. A single
# injected fault may cascade into additional findings (e.g. a corrupted
# counterpart also breaks its pair) — the property only demands that the
# injected line/check pair is reported (Req 4.11).


def _inject_json_garbage(draw, items):
    idx = draw(st.integers(0, len(items) - 1))
    items[idx] = draw(st.sampled_from(GARBAGE_LINES))  # replaced verbatim
    return idx + 1, "json_parse"


def _inject_missing_field(draw, items):
    idx = draw(st.integers(0, len(items) - 1))
    field = draw(st.sampled_from(REQUIRED_FIELDS))
    del items[idx][field]
    return idx + 1, "required_fields"


def _inject_empty_question(draw, items):
    idx = draw(st.integers(0, len(items) - 1))
    items[idx]["question"] = ""
    return idx + 1, "required_fields"


def _inject_wrong_type(draw, items):
    idx = draw(st.integers(0, len(items) - 1))
    items[idx]["expected_source_ids"] = draw(
        st.sampled_from(["Quran 1:1", 42, {"a": 1}, [1, 2], None])
    )
    return idx + 1, "required_fields"


def _inject_invalid_language(draw, items):
    idx = draw(st.integers(0, len(items) - 1))
    items[idx]["language"] = draw(st.sampled_from(INVALID_LANGUAGES))
    return idx + 1, "allowed_values"


def _inject_invalid_category(draw, items):
    idx = draw(st.integers(0, len(items) - 1))
    items[idx]["category"] = draw(st.sampled_from(INVALID_CATEGORIES))
    return idx + 1, "allowed_values"


def _inject_malformed_source_id(draw, items):
    idx = _pick_index(draw, items, lambda i: i["category"] != "out_of_corpus")
    bad = draw(st.sampled_from(MALFORMED_SOURCE_IDS))
    items[idx]["expected_source_ids"] = items[idx]["expected_source_ids"] + [bad]
    return idx + 1, "source_id_format"


def _inject_ooc_with_ids(draw, items):
    idx = _pick_index(draw, items, lambda i: i["category"] == "out_of_corpus")
    items[idx]["expected_source_ids"] = ["Quran 1:1"]
    return idx + 1, "category_consistency"


def _inject_non_ooc_empty_ids(draw, items):
    idx = _pick_index(
        draw, items, lambda i: i["category"] in ("direct_lookup", "paraphrase")
    )
    items[idx]["expected_source_ids"] = []
    return idx + 1, "category_consistency"


def _inject_missing_counterpart_field(draw, items):
    idx = _pick_index(draw, items, lambda i: i["category"] == "cross_lingual")
    variant = draw(st.sampled_from(["delete", "null", "empty"]))
    if variant == "delete":
        del items[idx]["counterpart_id"]
    elif variant == "null":
        items[idx]["counterpart_id"] = None
    else:
        items[idx]["counterpart_id"] = ""
    return idx + 1, "counterpart_required"


def _inject_dangling_counterpart(draw, items):
    idx = _pick_index(draw, items, lambda i: i["category"] == "cross_lingual")
    items[idx]["counterpart_id"] = NONEXISTENT_ID
    return idx + 1, "counterpart_reference"


def _inject_same_language_counterpart(draw, items):
    idx = _pick_index(draw, items, lambda i: i["category"] == "cross_lingual")
    language = items[idx]["language"]
    other = _pick_index(
        draw,
        items,
        lambda i: i["language"] == language and i["category"] == "direct_lookup",
    )
    items[idx]["counterpart_id"] = items[other]["id"]
    return idx + 1, "counterpart_reference"


def _inject_mismatched_counterpart_ids(draw, items):
    idx = _pick_index(draw, items, lambda i: i["category"] == "cross_lingual")
    items[idx]["expected_source_ids"] = items[idx]["expected_source_ids"] + [
        FOREIGN_SOURCE_ID
    ]
    return idx + 1, "counterpart_reference"


def _inject_duplicate_id(draw, items):
    first = draw(st.integers(0, len(items) - 2))
    second = draw(st.integers(first + 1, len(items) - 1))
    items[second]["id"] = items[first]["id"]
    # Duplicates are flagged at the line of the *second* occurrence.
    return second + 1, "id_uniqueness"


def _inject_too_few_items(draw, items):
    keep = draw(st.integers(1, 20))  # well below the 50-item floor (Req 4.2)
    del items[keep:]
    return 0, "dataset_counts"


def _inject_too_many_items(draw, items):
    # Pad with fresh valid items until the total exceeds 100 (Req 4.2).
    target = draw(st.integers(101, 105))
    for n in range(target - len(items)):
        items.append(
            {
                "id": f"zz-extra-{n:03d}",
                "question": f"padding question {n}",
                "language": "en",
                "category": "direct_lookup",
                "expected_source_ids": ["Quran 1:1"],
            }
        )
    return 0, "dataset_counts"


FAULTS = {
    "json_garbage": _inject_json_garbage,
    "missing_field": _inject_missing_field,
    "empty_question": _inject_empty_question,
    "wrong_type_ids": _inject_wrong_type,
    "invalid_language": _inject_invalid_language,
    "invalid_category": _inject_invalid_category,
    "malformed_source_id": _inject_malformed_source_id,
    "ooc_with_ids": _inject_ooc_with_ids,
    "non_ooc_empty_ids": _inject_non_ooc_empty_ids,
    "missing_counterpart_field": _inject_missing_counterpart_field,
    "dangling_counterpart": _inject_dangling_counterpart,
    "same_language_counterpart": _inject_same_language_counterpart,
    "mismatched_counterpart_ids": _inject_mismatched_counterpart_ids,
    "duplicate_id": _inject_duplicate_id,
    "too_few_items": _inject_too_few_items,
    "too_many_items": _inject_too_many_items,
}


@st.composite
def corrupted_datasets(draw):
    """A valid Golden_Dataset with exactly one injected violation.

    Returns (fault_name, jsonl_lines, expected_line, expected_check): the
    serialized file lines plus the (line_number, check_name) finding the
    loader must report for the injected fault.
    """
    items = copy.deepcopy(draw(golden_dataset_dicts()))
    fault_name = draw(st.sampled_from(sorted(FAULTS)))
    expected_line, expected_check = FAULTS[fault_name](draw, items)
    lines = [
        entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
        for entry in items
    ]
    return fault_name, lines, expected_line, expected_check


def _write_dataset(tmp_dir: str, lines: list[str]) -> Path:
    path = Path(tmp_dir) / "golden_dataset.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.with_suffix(".meta.json").write_text(
        json.dumps({"version": "1.0.0"}), encoding="utf-8"
    )
    return path


class TestProperty14DatasetValidation:
    # deadline=None: each example writes real files; filesystem latency
    # jitter must not fail otherwise-passing examples.
    @settings(max_examples=100, deadline=None)
    @given(items=golden_dataset_dicts())
    def test_any_valid_dataset_loads_without_error(self, items):
        """Every generated valid Golden_Dataset passes the full validation
        suite (Req 4.2, 4.3, 4.4, 4.6, 4.7, 4.8, 4.9, 4.10)."""
        lines = [json.dumps(item, ensure_ascii=False) for item in items]
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset = DatasetLoader().load(_write_dataset(tmp_dir, lines))
        assert len(dataset.items) == len(items)

    @settings(max_examples=100, deadline=None)
    @given(data=corrupted_datasets())
    def test_any_single_violation_is_rejected_with_line_and_check(self, data):
        """Injecting one random violation into a valid dataset makes the
        loader reject the entire file with a DatasetValidationError whose
        findings include the injected fault's line number and check name
        (Req 4.10, 4.11)."""
        fault_name, lines, expected_line, expected_check = data
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_dataset(tmp_dir, lines)
            with pytest.raises(DatasetValidationError) as excinfo:
                DatasetLoader().load(path)

        findings = {(line, check) for line, check, _ in excinfo.value.errors}
        assert (expected_line, expected_check) in findings, (
            f"fault {fault_name!r}: expected finding "
            f"(line {expected_line}, check {expected_check!r}) "
            f"not among reported findings {sorted(findings)}"
        )
        # Every finding carries a non-empty human-readable message (Req 4.11).
        assert all(message for _, _, message in excinfo.value.errors)
