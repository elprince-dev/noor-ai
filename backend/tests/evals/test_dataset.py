"""Tests for DatasetLoader — golden dataset load/validate/version.

Covers Req 4.10, 4.11 (validation with line-level findings, whole-file
rejection), Req 5.1 (content-sensitive version), Req 5.4 (undeterminable
version is a distinct error).
"""
import json
from pathlib import Path

import pytest

from evals.dataset import (
    DatasetLoader,
    DatasetValidationError,
    DatasetVersionError,
    GoldenDataset,
)


def make_item(**overrides) -> dict:
    """A representative valid Golden_Item; fields overridable per test."""
    item = {
        "id": "en-direct-001",
        "question": "What does the Quran say about backbiting?",
        "language": "en",
        "category": "direct_lookup",
        "expected_source_ids": ["Quran 49:12"],
        "counterpart_id": None,
        "reference_answer": None,
    }
    item.update(overrides)
    return item


def make_valid_items() -> list[dict]:
    """50 items meeting every dataset-level count constraint.

    25 Arabic + 25 English; 20 direct_lookup, 10 paraphrase,
    10 cross_lingual (5 linked pairs), 10 out_of_corpus.
    """
    items: list[dict] = []
    for lang, question in (("ar", "ما حكم الغيبة؟"), ("en", "What about backbiting?")):
        for n in range(10):
            items.append(
                make_item(
                    id=f"{lang}-direct-{n:03d}",
                    question=f"{question} {n}",
                    language=lang,
                    category="direct_lookup",
                    expected_source_ids=[f"Quran 49:{n + 1}"],
                )
            )
        for n in range(5):
            items.append(
                make_item(
                    id=f"{lang}-para-{n:03d}",
                    question=f"{question} p{n}",
                    language=lang,
                    category="paraphrase",
                    expected_source_ids=[f"Sahih al-Bukhari {n + 1}"],
                )
            )
        for n in range(5):
            items.append(
                make_item(
                    id=f"{lang}-ooc-{n:03d}",
                    question=f"{question} x{n}",
                    language=lang,
                    category="out_of_corpus",
                    expected_source_ids=[],
                )
            )
    for n in range(5):
        items.append(
            make_item(
                id=f"ar-cross-{n:03d}",
                question=f"سؤال متقاطع {n}",
                language="ar",
                category="cross_lingual",
                expected_source_ids=[f"Sahih Muslim {n + 1}"],
                counterpart_id=f"en-cross-{n:03d}",
            )
        )
        items.append(
            make_item(
                id=f"en-cross-{n:03d}",
                question=f"Cross-lingual question {n}",
                language="en",
                category="cross_lingual",
                expected_source_ids=[f"Sahih Muslim {n + 1}"],
                counterpart_id=f"ar-cross-{n:03d}",
            )
        )
    return items


def write_dataset(
    tmp_path: Path,
    items: list[dict] | None = None,
    *,
    raw_lines: list[str] | None = None,
    meta: dict | str | None = None,
) -> Path:
    """Write golden_dataset.jsonl + golden_dataset.meta.json into tmp_path."""
    lines = raw_lines if raw_lines is not None else [
        json.dumps(item, ensure_ascii=False) for item in (items or make_valid_items())
    ]
    path = tmp_path / "golden_dataset.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if meta is None:
        meta = {"version": "1.0.0"}
    meta_text = meta if isinstance(meta, str) else json.dumps(meta)
    (tmp_path / "golden_dataset.meta.json").write_text(meta_text, encoding="utf-8")
    return path


def checks_for(exc_info) -> set[str]:
    return {check for _, check, _ in exc_info.value.errors}


class TestLoadValid:
    def test_loads_all_items_with_fields_intact(self, tmp_path):
        dataset = DatasetLoader().load(write_dataset(tmp_path))
        assert isinstance(dataset, GoldenDataset)
        assert len(dataset.items) == 50
        first = dataset.items[0]
        assert first.id == "ar-direct-000"
        assert first.question == "ما حكم الغيبة؟ 0"
        assert first.expected_source_ids == ("Quran 49:1",)

    def test_effective_version_combines_meta_label_and_content_hash(self, tmp_path):
        dataset = DatasetLoader().load(write_dataset(tmp_path, meta={"version": "2.1.0"}))
        label, _, digest = dataset.version.partition("+")
        assert label == "2.1.0"
        assert len(digest) == 12
        assert all(c in "0123456789abcdef" for c in digest)

    def test_version_changes_when_content_changes(self, tmp_path):
        """Distinct item content ⇒ distinct version identifier (Req 5.1)."""
        loader = DatasetLoader()
        v1 = loader.load(write_dataset(tmp_path)).version
        items = make_valid_items()
        items[0]["question"] += " (edited)"
        v2 = loader.load(write_dataset(tmp_path, items)).version
        assert v1 != v2

    def test_tolerates_trailing_blank_line(self, tmp_path):
        lines = [json.dumps(i, ensure_ascii=False) for i in make_valid_items()]
        path = write_dataset(tmp_path, raw_lines=lines + [""])
        assert len(DatasetLoader().load(path).items) == 50


class TestVersionUndeterminable:
    def test_missing_jsonl_file(self, tmp_path):
        with pytest.raises(DatasetVersionError, match="undeterminable"):
            DatasetLoader().load(tmp_path / "missing.jsonl")

    def test_missing_meta_file(self, tmp_path):
        path = write_dataset(tmp_path)
        (tmp_path / "golden_dataset.meta.json").unlink()
        with pytest.raises(DatasetVersionError, match="undeterminable"):
            DatasetLoader().load(path)

    def test_malformed_meta_file(self, tmp_path):
        path = write_dataset(tmp_path, meta="not json {")
        with pytest.raises(DatasetVersionError, match="undeterminable"):
            DatasetLoader().load(path)

    def test_meta_without_version_string(self, tmp_path):
        path = write_dataset(tmp_path, meta={"description": "no version"})
        with pytest.raises(DatasetVersionError, match="undeterminable"):
            DatasetLoader().load(path)

    def test_version_error_is_distinct_from_validation_error(self):
        assert not issubclass(DatasetVersionError, DatasetValidationError)
        assert not issubclass(DatasetValidationError, DatasetVersionError)


class TestPerLineValidation:
    def load_with_bad_item(self, tmp_path, bad_item: dict, position: int = 0):
        items = make_valid_items()
        items[position] = bad_item
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        return exc_info

    def test_unparseable_line_reports_line_number(self, tmp_path):
        lines = [json.dumps(i, ensure_ascii=False) for i in make_valid_items()]
        lines[2] = "{not json"
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, raw_lines=lines))
        assert (3, "json_parse") in {(n, c) for n, c, _ in exc_info.value.errors}

    def test_non_object_line_rejected(self, tmp_path):
        lines = [json.dumps(i, ensure_ascii=False) for i in make_valid_items()]
        lines[0] = '["an", "array"]'
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, raw_lines=lines))
        assert "json_parse" in checks_for(exc_info)

    def test_missing_required_field(self, tmp_path):
        bad = make_item(id="en-direct-000")
        del bad["question"]
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "required_fields" in checks_for(exc_info)

    def test_empty_question_rejected(self, tmp_path):
        bad = make_item(id="en-direct-000", question="")
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "required_fields" in checks_for(exc_info)

    def test_wrong_type_expected_source_ids(self, tmp_path):
        bad = make_item(id="en-direct-000", expected_source_ids="Quran 49:12")
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "required_fields" in checks_for(exc_info)

    def test_invalid_language(self, tmp_path):
        bad = make_item(id="en-direct-000", language="fr")
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "allowed_values" in checks_for(exc_info)

    def test_invalid_category(self, tmp_path):
        bad = make_item(id="en-direct-000", category="trivia")
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "allowed_values" in checks_for(exc_info)

    @pytest.mark.parametrize(
        "source_id",
        ["Quran 49", "quran 49:12", "Sahih Bukhari 1", "Sahih al-Bukhari", "Quran 49:12 "],
    )
    def test_invalid_source_id_grammar(self, tmp_path, source_id):
        bad = make_item(id="en-direct-000", expected_source_ids=[source_id])
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "source_id_format" in checks_for(exc_info)

    def test_out_of_corpus_with_source_ids_rejected(self, tmp_path):
        bad = make_item(
            id="en-ooc-000", category="out_of_corpus", expected_source_ids=["Quran 1:1"]
        )
        exc_info = self.load_with_bad_item(tmp_path, bad, position=35)
        assert "category_consistency" in checks_for(exc_info)

    def test_non_out_of_corpus_with_empty_ids_rejected(self, tmp_path):
        bad = make_item(id="en-direct-000", expected_source_ids=[])
        exc_info = self.load_with_bad_item(tmp_path, bad, position=10)
        assert "category_consistency" in checks_for(exc_info)

    def test_cross_lingual_without_counterpart_id_rejected(self, tmp_path):
        bad = make_item(
            id="ar-cross-000",
            language="ar",
            category="cross_lingual",
            expected_source_ids=["Sahih Muslim 1"],
            counterpart_id=None,
        )
        exc_info = self.load_with_bad_item(tmp_path, bad, position=40)
        assert "counterpart_required" in checks_for(exc_info)


class TestCrossLineValidation:
    def test_duplicate_ids_rejected(self, tmp_path):
        items = make_valid_items()
        items[1]["id"] = items[0]["id"]
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        assert "id_uniqueness" in checks_for(exc_info)

    def test_counterpart_must_exist(self, tmp_path):
        items = make_valid_items()
        cross = next(i for i in items if i["category"] == "cross_lingual")
        cross["counterpart_id"] = "does-not-exist"
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        assert "counterpart_reference" in checks_for(exc_info)

    def test_counterpart_must_be_other_language(self, tmp_path):
        items = make_valid_items()
        ar_cross = next(
            i for i in items if i["category"] == "cross_lingual" and i["language"] == "ar"
        )
        # Point the Arabic item at another Arabic cross-lingual item.
        other_ar = next(
            i
            for i in items
            if i["category"] == "cross_lingual"
            and i["language"] == "ar"
            and i["id"] != ar_cross["id"]
        )
        ar_cross["counterpart_id"] = other_ar["id"]
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        assert "counterpart_reference" in checks_for(exc_info)

    def test_counterpart_must_share_expected_source_id_set(self, tmp_path):
        items = make_valid_items()
        ar_cross = next(
            i for i in items if i["category"] == "cross_lingual" and i["language"] == "ar"
        )
        ar_cross["expected_source_ids"] = ["Quran 2:255"]
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        assert "counterpart_reference" in checks_for(exc_info)


class TestDatasetCounts:
    def test_too_few_items_rejected(self, tmp_path):
        items = make_valid_items()[:30]
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        assert "dataset_counts" in checks_for(exc_info)

    def test_too_many_items_rejected(self, tmp_path):
        items = make_valid_items()
        for n in range(51):
            items.append(
                make_item(
                    id=f"en-extra-{n:03d}",
                    question=f"Extra question {n}",
                    expected_source_ids=["Quran 1:1"],
                )
            )
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        assert "dataset_counts" in checks_for(exc_info)

    def test_count_error_uses_line_number_zero(self, tmp_path):
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, make_valid_items()[:10]))
        assert all(n == 0 for n, check, _ in exc_info.value.errors if check == "dataset_counts")


class TestWholeFileRejection:
    def test_single_bad_line_rejects_entire_file_and_collects_all_errors(self, tmp_path):
        """Any failure rejects the whole file, reporting each finding (Req 4.11)."""
        items = make_valid_items()
        items[0]["language"] = "fr"
        items[5]["expected_source_ids"] = ["bad id"]
        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetLoader().load(write_dataset(tmp_path, items))
        checks = checks_for(exc_info)
        assert {"allowed_values", "source_id_format"} <= checks
