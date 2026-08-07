"""Golden dataset loading, validation, and versioning (Req 4.10, 4.11, 5.1, 5.2, 5.4).

`DatasetLoader.load(path)` reads a UTF-8 JSONL file of Golden_Items, runs the
full validation suite (per-line checks in order, then cross-line, then
dataset-level counts), and returns a `GoldenDataset` carrying the items plus
the effective version identifier `"{meta.version}+{sha256(jsonl_bytes)[:12]}"`.

Two failure modes are deliberately distinct:
- `DatasetVersionError` — the version identifier cannot be determined
  (missing/unreadable jsonl or meta file, malformed manifest). The harness
  must abort before executing any item (Req 5.4).
- `DatasetValidationError` — the files were readable but one or more
  Golden_Items failed validation; carries every finding as
  `(line_number, check_name, message)` and rejects the whole file (Req 4.11).
"""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

LANGUAGES = frozenset({"ar", "en"})
CATEGORIES = frozenset({"direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus"})

# Source_ID grammar — identical to the corpus citation metadata (design §5).
SOURCE_ID_PATTERNS = (
    re.compile(r"^Quran \d+:\d+$"),
    re.compile(r"^Sahih (al-Bukhari|Muslim) \d+$"),
)

MIN_ITEMS = 50
MAX_ITEMS = 100
MIN_PER_LANGUAGE = 20
MIN_PER_CATEGORY = 5


class DatasetVersionError(Exception):
    """The Golden_Dataset version identifier could not be determined (Req 5.4)."""


class DatasetValidationError(Exception):
    """One or more Golden_Items failed validation; the whole file is rejected.

    `errors` is a list of `(line_number, check_name, message)` tuples.
    Dataset-level findings (counts) use line_number 0.
    """

    def __init__(self, errors: list[tuple[int, str, str]]):
        self.errors = errors
        summary = "; ".join(f"line {n} [{check}]: {msg}" for n, check, msg in errors)
        super().__init__(f"golden dataset validation failed ({len(errors)} error(s)): {summary}")


@dataclass(frozen=True, slots=True)
class GoldenItem:
    """One validated row of the Golden_Dataset (design §5 data model)."""

    id: str
    question: str
    language: str  # "ar" | "en"
    category: str  # direct_lookup | paraphrase | cross_lingual | out_of_corpus
    expected_source_ids: tuple[str, ...]
    counterpart_id: str | None = None
    reference_answer: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "language": self.language,
            "category": self.category,
            "expected_source_ids": list(self.expected_source_ids),
            "counterpart_id": self.counterpart_id,
            "reference_answer": self.reference_answer,
        }


@dataclass(frozen=True, slots=True)
class GoldenDataset:
    """A validated Golden_Dataset: its items and effective version identifier."""

    items: tuple[GoldenItem, ...]
    version: str


def is_valid_source_id(source_id: str) -> bool:
    """True when `source_id` conforms to the corpus citation grammar."""
    return any(p.match(source_id) for p in SOURCE_ID_PATTERNS)


class DatasetLoader:
    """Loads, validates, and versions the Golden_Dataset JSONL file."""

    def load(self, path: str | Path) -> GoldenDataset:
        """Load and fully validate the dataset at `path`.

        Raises:
            DatasetVersionError: version undeterminable — jsonl or meta file
                missing/unreadable, or the manifest lacks a version (Req 5.4).
            DatasetValidationError: any Golden_Item or dataset-level check
                failed; carries every `(line, check, message)` finding and
                rejects the entire file (Req 4.10, 4.11).
        """
        path = Path(path)
        jsonl_bytes = self._read_jsonl_bytes(path)
        version = self._effective_version(path, jsonl_bytes)

        errors: list[tuple[int, str, str]] = []
        items = self._parse_and_validate_lines(jsonl_bytes, errors)
        self._validate_cross_line(items, errors)
        self._validate_dataset_counts([item for _, item in items], errors)

        if errors:
            raise DatasetValidationError(errors)
        return GoldenDataset(items=tuple(item for _, item in items), version=version)

    # -- version determination (Req 5.1, 5.4) --------------------------------

    def _read_jsonl_bytes(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise DatasetVersionError(
                f"dataset version undeterminable: cannot read dataset file {path}: {exc}"
            ) from exc

    def _effective_version(self, path: Path, jsonl_bytes: bytes) -> str:
        """`"{meta.version}+{sha256(jsonl_bytes)[:12]}"` (design §5)."""
        meta_path = path.with_suffix(".meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetVersionError(
                f"dataset version undeterminable: cannot read manifest {meta_path}: {exc}"
            ) from exc
        label = meta.get("version") if isinstance(meta, dict) else None
        if not isinstance(label, str) or not label:
            raise DatasetVersionError(
                f"dataset version undeterminable: manifest {meta_path} has no 'version' string"
            )
        content_hash = hashlib.sha256(jsonl_bytes).hexdigest()[:12]
        return f"{label}+{content_hash}"

    # -- per-line checks, in design order -------------------------------------

    def _parse_and_validate_lines(
        self, jsonl_bytes: bytes, errors: list[tuple[int, str, str]]
    ) -> list[tuple[int, GoldenItem]]:
        """Parse each line and run per-line checks 1–6; returns (line, item) pairs."""
        items: list[tuple[int, GoldenItem]] = []
        text = jsonl_bytes.decode("utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue  # tolerate blank lines (e.g. trailing newline)
            item = self._validate_line(line_number, line, errors)
            if item is not None:
                items.append((line_number, item))
        return items

    def _validate_line(
        self, line_number: int, line: str, errors: list[tuple[int, str, str]]
    ) -> GoldenItem | None:
        # Check 1: line parses as a JSON object.
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append((line_number, "json_parse", f"line is not valid JSON: {exc}"))
            return None
        if not isinstance(raw, dict):
            errors.append((line_number, "json_parse", "line is not a JSON object"))
            return None

        # Check 2: required fields present with correct types.
        field_errors = self._check_required_fields(raw)
        if field_errors:
            errors.extend((line_number, "required_fields", msg) for msg in field_errors)
            return None

        # Check 3: allowed language and category values.
        value_errors = []
        if raw["language"] not in LANGUAGES:
            value_errors.append(
                f"language must be one of {sorted(LANGUAGES)}, got {raw['language']!r}"
            )
        if raw["category"] not in CATEGORIES:
            value_errors.append(
                f"category must be one of {sorted(CATEGORIES)}, got {raw['category']!r}"
            )
        if value_errors:
            errors.extend((line_number, "allowed_values", msg) for msg in value_errors)
            return None

        ok = True

        # Check 4: every expected Source_ID matches the citation grammar.
        for source_id in raw["expected_source_ids"]:
            if not is_valid_source_id(source_id):
                errors.append(
                    (
                        line_number,
                        "source_id_format",
                        f"expected Source_ID {source_id!r} does not match "
                        "'Quran S:A' or 'Sahih al-Bukhari/Muslim N'",
                    )
                )
                ok = False

        # Check 5: category-consistent expected Source_ID lists (Req 4.8, 4.9).
        if raw["category"] == "out_of_corpus":
            if raw["expected_source_ids"]:
                errors.append(
                    (
                        line_number,
                        "category_consistency",
                        "out_of_corpus items must have empty expected_source_ids",
                    )
                )
                ok = False
        elif not raw["expected_source_ids"]:
            errors.append(
                (
                    line_number,
                    "category_consistency",
                    f"{raw['category']} items must have at least one expected Source_ID",
                )
            )
            ok = False

        # Check 6: cross_lingual requires a counterpart_id.
        if raw["category"] == "cross_lingual" and not raw.get("counterpart_id"):
            errors.append(
                (
                    line_number,
                    "counterpart_required",
                    "cross_lingual items must carry a counterpart_id",
                )
            )
            ok = False

        if not ok:
            return None
        return GoldenItem(
            id=raw["id"],
            question=raw["question"],
            language=raw["language"],
            category=raw["category"],
            expected_source_ids=tuple(raw["expected_source_ids"]),
            counterpart_id=raw.get("counterpart_id"),
            reference_answer=raw.get("reference_answer"),
        )

    @staticmethod
    def _check_required_fields(raw: dict) -> list[str]:
        msgs: list[str] = []
        for name in ("id", "question", "language", "category"):
            value = raw.get(name)
            if not isinstance(value, str) or not value:
                msgs.append(f"'{name}' must be a non-empty string")
        ids = raw.get("expected_source_ids")
        if not isinstance(ids, list) or not all(isinstance(s, str) for s in ids):
            msgs.append("'expected_source_ids' must be a list of strings")
        counterpart = raw.get("counterpart_id")
        if counterpart is not None and not isinstance(counterpart, str):
            msgs.append("'counterpart_id' must be a string or null")
        reference = raw.get("reference_answer")
        if reference is not None and not isinstance(reference, str):
            msgs.append("'reference_answer' must be a string or null")
        return msgs

    # -- cross-line checks (design check 7) ------------------------------------

    def _validate_cross_line(
        self, items: list[tuple[int, GoldenItem]], errors: list[tuple[int, str, str]]
    ) -> None:
        by_id: dict[str, GoldenItem] = {}
        for line_number, item in items:
            if item.id in by_id:
                errors.append(
                    (line_number, "id_uniqueness", f"duplicate item id {item.id!r}")
                )
            else:
                by_id[item.id] = item

        for line_number, item in items:
            if item.category != "cross_lingual":
                continue
            counterpart = by_id.get(item.counterpart_id or "")
            if counterpart is None:
                errors.append(
                    (
                        line_number,
                        "counterpart_reference",
                        f"counterpart_id {item.counterpart_id!r} does not exist in the dataset",
                    )
                )
                continue
            if counterpart.language == item.language:
                errors.append(
                    (
                        line_number,
                        "counterpart_reference",
                        f"counterpart {item.counterpart_id!r} must be in the other language",
                    )
                )
            if set(counterpart.expected_source_ids) != set(item.expected_source_ids):
                errors.append(
                    (
                        line_number,
                        "counterpart_reference",
                        f"counterpart {item.counterpart_id!r} must share the same "
                        "expected Source_ID set",
                    )
                )

    # -- dataset-level counts (design check 8, Req 4.2, 4.3, 4.6) --------------

    def _validate_dataset_counts(
        self, items: list[GoldenItem], errors: list[tuple[int, str, str]]
    ) -> None:
        total = len(items)
        if not MIN_ITEMS <= total <= MAX_ITEMS:
            errors.append(
                (
                    0,
                    "dataset_counts",
                    f"dataset must contain {MIN_ITEMS}-{MAX_ITEMS} items, got {total}",
                )
            )
        for language in sorted(LANGUAGES):
            count = sum(1 for item in items if item.language == language)
            if count < MIN_PER_LANGUAGE:
                errors.append(
                    (
                        0,
                        "dataset_counts",
                        f"dataset must contain at least {MIN_PER_LANGUAGE} "
                        f"{language!r} items, got {count}",
                    )
                )
        for category in sorted(CATEGORIES):
            count = sum(1 for item in items if item.category == category)
            if count < MIN_PER_CATEGORY:
                errors.append(
                    (
                        0,
                        "dataset_counts",
                        f"dataset must contain at least {MIN_PER_CATEGORY} "
                        f"{category!r} items, got {count}",
                    )
                )
