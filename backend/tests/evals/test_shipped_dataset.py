"""The shipped golden dataset passes DatasetLoader validation (Task 7.6).

Loads the real `backend/evals/data/golden_dataset.jsonl` through
`DatasetLoader` — proving the count constraints hold on the actual
committed data (Req 4.2, 4.3, 4.6).
"""
from collections import Counter
from pathlib import Path

import pytest

from evals.dataset import (
    CATEGORIES,
    LANGUAGES,
    MIN_PER_CATEGORY,
    MIN_PER_LANGUAGE,
    DatasetLoader,
    GoldenDataset,
)

SHIPPED_DATASET = (
    Path(__file__).resolve().parents[2] / "evals" / "data" / "golden_dataset.jsonl"
)


@pytest.fixture(scope="module")
def dataset() -> GoldenDataset:
    """The shipped dataset, loaded once — loading itself must not raise."""
    return DatasetLoader().load(SHIPPED_DATASET)


def test_shipped_dataset_file_exists():
    assert SHIPPED_DATASET.is_file(), f"shipped dataset missing at {SHIPPED_DATASET}"


def test_shipped_dataset_loads_without_error(dataset):
    assert isinstance(dataset, GoldenDataset)
    assert dataset.items


def test_total_item_count_within_bounds(dataset):
    """Req 4.2: 50–100 Golden_Items."""
    assert 50 <= len(dataset.items) <= 100


def test_at_least_20_items_per_language(dataset):
    """Req 4.3: at least 20 Arabic and 20 English items."""
    by_language = Counter(item.language for item in dataset.items)
    for language in sorted(LANGUAGES):
        assert by_language[language] >= MIN_PER_LANGUAGE, (
            f"expected >= {MIN_PER_LANGUAGE} {language!r} items, "
            f"got {by_language[language]}"
        )


def test_at_least_5_items_per_category(dataset):
    """Req 4.6: at least 5 items in each category."""
    by_category = Counter(item.category for item in dataset.items)
    for category in sorted(CATEGORIES):
        assert by_category[category] >= MIN_PER_CATEGORY, (
            f"expected >= {MIN_PER_CATEGORY} {category!r} items, "
            f"got {by_category[category]}"
        )


def test_effective_version_starts_with_manifest_label(dataset):
    """Manifest starts at 1.0.0; effective version is '1.0.0+{hash12}'."""
    assert dataset.version.startswith("1.0.0+")
    digest = dataset.version.removeprefix("1.0.0+")
    assert len(digest) == 12
    assert all(c in "0123456789abcdef" for c in digest)
