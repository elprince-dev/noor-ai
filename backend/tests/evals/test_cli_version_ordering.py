"""Unit test: dataset version resolved before first item execution (Req 5.2).

Task 11.7 — plain pytest unit test (not a property test) over the CLI
composition root `evals.cli._cmd_run`. The Golden_Dataset version identifier
is resolved inside `DatasetLoader.load`, so proving Req 5.2 means proving
call ordering: `load` completes before the first pipeline-client call for
any Golden_Item.

Strategy: a shared call log. `DatasetLoader.load` is wrapped to append
"dataset.load" *after* the real load (and hence version resolution)
completes; recording fakes are patched over the production adapters the CLI
lazily imports (`SrcRetrievalClient`, `SrcGenerationClient`, `NovaJudge`),
each appending to the same log per call. Asserting the load entry precedes
every client entry proves the ordering.

Abort path (Req 5.4 feeding 5.2): a missing `golden_dataset.meta.json`
makes the version undeterminable — `load` raises `DatasetVersionError`, the
CLI aborts, and the log shows zero client calls: no item ever executed.

Everything runs in-memory / against tmp_path — no AWS calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.cli import _cmd_run
from evals.dataset import DatasetLoader
from evals.judge import Verdict
from evals.pipeline import RetrievalResult

# -- valid on-disk dataset + config fixtures ----------------------------------


def _golden_items() -> list[dict]:
    """50 valid Golden_Items: 25 per language, every category >= 5."""
    items: list[dict] = []
    for lang in ("ar", "en"):
        other = "en" if lang == "ar" else "ar"
        for i in range(10):
            items.append(
                {
                    "id": f"{lang}-direct-{i}",
                    "question": f"direct question {lang} {i}",
                    "language": lang,
                    "category": "direct_lookup",
                    "expected_source_ids": ["Quran 2:255"],
                }
            )
        for i in range(6):
            items.append(
                {
                    "id": f"{lang}-para-{i}",
                    "question": f"paraphrase question {lang} {i}",
                    "language": lang,
                    "category": "paraphrase",
                    "expected_source_ids": ["Sahih al-Bukhari 1"],
                }
            )
        for i in range(6):
            items.append(
                {
                    "id": f"{lang}-ooc-{i}",
                    "question": f"out of corpus question {lang} {i}",
                    "language": lang,
                    "category": "out_of_corpus",
                    "expected_source_ids": [],
                }
            )
        for i in range(3):
            items.append(
                {
                    "id": f"{lang}-cross-{i}",
                    "question": f"cross lingual question {lang} {i}",
                    "language": lang,
                    "category": "cross_lingual",
                    "expected_source_ids": ["Quran 1:1"],
                    "counterpart_id": f"{other}-cross-{i}",
                }
            )
    return items


def _write_eval_files(tmp_path: Path, *, with_meta: bool = True) -> Path:
    """Write a valid dataset (optionally its manifest) and config; return config path."""
    jsonl_path = tmp_path / "golden_dataset.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(item) for item in _golden_items()) + "\n",
        encoding="utf-8",
    )
    if with_meta:
        (tmp_path / "golden_dataset.meta.json").write_text(
            json.dumps({"version": "1.0.0"}), encoding="utf-8"
        )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model_id: us.anthropic.claude-haiku-4-5-20251001-v1:0\n"
        "retrieval_top_k: 3\n"
        "prompt_version: v1\n"
        "judge_model_id: us.amazon.nova-pro-v1:0\n"
        "dataset_path: golden_dataset.jsonl\n"
        "results_dir: results\n",
        encoding="utf-8",
    )
    return config_path


# -- recording stubs -----------------------------------------------------------


def _install_recording_stubs(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    """Patch DatasetLoader.load (wrapping the real one) and replace the
    AWS-facing adapters the CLI lazily imports with in-memory fakes that
    append to the shared `calls` log."""

    real_load = DatasetLoader.load

    def recording_load(self: DatasetLoader, path):  # noqa: ANN001
        dataset = real_load(self, path)
        # Appended only after the real load — and therefore the version
        # resolution inside it — has completed successfully.
        calls.append("dataset.load")
        return dataset

    monkeypatch.setattr(DatasetLoader, "load", recording_load)

    class FakeRetrievalClient:
        def retrieve(self, question: str, top_k: int) -> RetrievalResult:
            calls.append("client.retrieve")
            return RetrievalResult(
                sources=[("Quran 2:255", 0.9)],
                context="[Quran 2:255] Ayat al-Kursi text",
                texts=("Ayat al-Kursi text",),
            )

    class FakeGenerationClient:
        def __init__(self, model_id: str) -> None:
            self.model_id = model_id

        def generate(self, question: str, context: str, prompt_version: str) -> str:
            calls.append("client.generate")
            return "a generated answer"

    class FakeJudge:
        def __init__(self, model_id: str, client=None) -> None:  # noqa: ANN001
            self.model_id = model_id

        def score(self, rubric, item, answer, retrieved) -> Verdict:  # noqa: ANN001
            calls.append("client.judge")
            return Verdict(verdict="pass", rationale="stub verdict")

    monkeypatch.setattr("evals.pipeline.SrcRetrievalClient", FakeRetrievalClient)
    monkeypatch.setattr("evals.pipeline.SrcGenerationClient", FakeGenerationClient)
    monkeypatch.setattr("evals.judge.NovaJudge", FakeJudge)


CLIENT_CALLS = {"client.retrieve", "client.generate", "client.judge"}


# -- tests ----------------------------------------------------------------------


def test_dataset_version_resolved_before_first_item_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req 5.2: DatasetLoader.load (which resolves the effective version)
    completes before the first pipeline-client call of any Golden_Item."""
    calls: list[str] = []
    _install_recording_stubs(monkeypatch, calls)
    config_path = _write_eval_files(tmp_path)

    exit_code = _cmd_run(str(config_path))

    assert exit_code == 0
    assert calls.count("dataset.load") == 1, (
        "the dataset (and its version) must be loaded exactly once per run"
    )
    client_indices = [i for i, c in enumerate(calls) if c in CLIENT_CALLS]
    assert client_indices, "with a valid dataset the items must actually execute"
    load_index = calls.index("dataset.load")
    assert load_index < client_indices[0], (
        f"dataset version must be resolved before the first item executes; "
        f"call log started {calls[: client_indices[0] + 1]!r}"
    )
    # Nothing at all touches the pipeline before the load completes.
    assert calls[0] == "dataset.load"


def test_undeterminable_version_prevents_any_item_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Req 5.2 abort path (via 5.4): a missing meta file makes the version
    undeterminable, the run aborts, and zero pipeline-client calls happen."""
    calls: list[str] = []
    _install_recording_stubs(monkeypatch, calls)
    config_path = _write_eval_files(tmp_path, with_meta=False)

    exit_code = _cmd_run(str(config_path))

    assert exit_code == 1
    assert "undeterminable" in capsys.readouterr().err
    assert not [c for c in calls if c in CLIENT_CALLS], (
        f"no Golden_Item may execute when the version is undeterminable; "
        f"observed client calls in {calls!r}"
    )
