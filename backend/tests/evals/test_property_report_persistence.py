"""Property 26: Report persistence is unique and append-only (design.md).

*For any* sequence of Eval_Harness runs persisted to the same results
location, every run receives a run identifier unique among all persisted
reports, and the bytes of every previously persisted report are unchanged
after each new persist.

**Validates: Requirements 9.1**

Pure filesystem Hypothesis test against tempfile directories — no AWS calls.
`ReportRepository` is exercised three ways:

- persisting any sequence of reports yields pairwise-distinct run ids, and
  each report loads back intact (with the run id injected);
- after persisting further reports, every previously written `report.json`
  is byte-identical to its snapshot (append-only);
- a scripted `run_id_factory` that repeats already-taken run ids forces the
  collision path: persist still succeeds under a fresh id and the colliding
  report's bytes are untouched.

`deadline=None` because each example performs real file I/O.
"""
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from evals.report import ReportRepository, generate_run_id

# -- strategies ----------------------------------------------------------------

# Free text in both scripts (Arabic content must survive persistence intact).
any_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
    ),
    max_size=40,
)

# JSON-safe leaf values for aggregates / per-item payloads.
json_leaves = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-1_000, 1_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    any_text,
)


@st.composite
def reports(draw) -> dict:
    """A small Eval_Report payload as `EvalRunner.run()` assembles it.

    Carries every Req 9.2 field except `run_id`, which `persist` injects.
    """
    per_item_count = draw(st.integers(0, 3))
    succeeded = draw(st.integers(0, per_item_count))
    return {
        "config": draw(
            st.fixed_dictionaries(
                {
                    "model_id": any_text,
                    "retrieval_top_k": st.integers(1, 20),
                    "prompt_version": st.sampled_from(["v1", "v2"]),
                }
            )
        ),
        "dataset_version": draw(any_text),
        "completed_at": draw(any_text),
        "aggregates": {
            "retrieval": draw(st.dictionaries(any_text, json_leaves, max_size=3)),
            "generation": draw(st.dictionaries(any_text, json_leaves, max_size=3)),
        },
        "per_item": [
            draw(st.dictionaries(any_text, json_leaves, min_size=1, max_size=3))
            for _ in range(per_item_count)
        ],
        "counts": {"succeeded": succeeded, "failed": per_item_count - succeeded},
    }


def snapshot_report_bytes(results_dir: Path) -> dict[str, bytes]:
    """Raw bytes of every persisted `report.json`, keyed by run id."""
    return {
        path.parent.name: path.read_bytes()
        for path in results_dir.glob("*/report.json")
    }


class TestProperty26ReportPersistenceUniqueAppendOnly:
    @settings(max_examples=100, deadline=None)
    @given(batch=st.lists(reports(), min_size=1, max_size=5))
    def test_run_ids_distinct_and_reports_load_back_intact(self, batch):
        """Persisting any sequence of reports to one results location yields
        pairwise-distinct run ids, and each report loads back equal to what
        was persisted, with the assigned run id injected (Req 9.1, 9.2)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = ReportRepository(tmp)
            run_ids = [repo.persist(report) for report in batch]

            assert len(set(run_ids)) == len(run_ids)
            for run_id, report in zip(run_ids, batch):
                assert repo.load(run_id) == {"run_id": run_id, **report}

    @settings(max_examples=100, deadline=None)
    @given(
        first_batch=st.lists(reports(), min_size=1, max_size=3),
        second_batch=st.lists(reports(), min_size=1, max_size=3),
    )
    def test_prior_reports_byte_identical_after_further_persists(
        self, first_batch, second_batch
    ):
        """After persisting more reports, every previously persisted
        `report.json` is byte-for-byte unchanged — the store is strictly
        append-only (Req 9.1)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = ReportRepository(tmp)
            for report in first_batch:
                repo.persist(report)
            before = snapshot_report_bytes(Path(tmp))

            new_ids = [repo.persist(report) for report in second_batch]

            after = snapshot_report_bytes(Path(tmp))
            # Every prior file survives with identical bytes.
            for run_id, original_bytes in before.items():
                assert after[run_id] == original_bytes
            # And exactly the new runs were added — nothing deleted.
            assert set(after) == set(before) | set(new_ids)

    @settings(max_examples=100, deadline=None)
    @given(
        existing=reports(),
        incoming=reports(),
        collision_count=st.integers(1, 4),
    )
    def test_collision_regenerates_and_leaves_existing_untouched(
        self, existing, incoming, collision_count
    ):
        """A run_id_factory scripted to repeat an already-taken id before
        yielding a fresh one still persists successfully under the fresh id,
        and the colliding report's bytes are untouched (Req 9.1)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = ReportRepository(tmp)
            taken_id = repo.persist(existing)
            existing_path = Path(tmp) / taken_id / "report.json"
            existing_bytes = existing_path.read_bytes()

            script = [taken_id] * collision_count + [generate_run_id()]
            calls = iter(script)
            colliding_repo = ReportRepository(tmp, run_id_factory=lambda: next(calls))

            new_id = colliding_repo.persist(incoming)

            assert new_id == script[-1]
            assert new_id != taken_id
            # Colliding report untouched, byte for byte.
            assert existing_path.read_bytes() == existing_bytes
            assert repo.load(taken_id) == {"run_id": taken_id, **existing}
            # The incoming report landed intact under the fresh id.
            assert repo.load(new_id) == {"run_id": new_id, **incoming}
