"""Property 18: Config validation aborts before execution (design.md
Correctness Properties).

*For any* Eval_Config with a randomly removed or wrongly-typed required
parameter, or with judge and generation models from the same model family
(across arbitrary Bedrock model-ID forms including regional prefixes), the
run aborts with an ``EvalConfigError`` identifying the problem before any
Golden_Item executes or any judge call is made — and any config with all
required well-typed parameters and cross-family models is accepted with the
exact configured values.

**Validates: Requirements 6.2, 6.8, 8.5, 8.8**

Pure filesystem-tmp Hypothesis test — no AWS calls. ``load_config`` is a pure
loader, so "aborts before execution" is exactly "raises EvalConfigError from
load_config": the CLI composition root only constructs the runner after a
config object exists. Files are written with ``tempfile`` inside the test
body because Hypothesis and the function-scoped pytest ``tmp_path`` fixture
interact poorly.
"""
import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.eval_config import EvalConfig, EvalConfigError, load_config

# -- strategy ingredients -----------------------------------------------------

# Bedrock vendor tokens (the "model family"), never colliding with the
# regional inference prefixes {us, eu, apac}.
VENDORS = ("anthropic", "amazon", "meta", "mistral", "cohere", "ai21")

# Optional cross-region inference profile prefixes (Req 8.8 / design §Property 18).
REGIONAL_PREFIXES = ("", "us.", "eu.", "apac.")

REQUIRED_FIELDS = ("model_id", "retrieval_top_k", "prompt_version", "judge_model_id")
OPTIONAL_FIELDS = ("dataset_path", "results_dir")

# Alphabet for model-ID suffixes: dot-free so the vendor token is always the
# first post-prefix segment (mirrors real IDs like "claude-haiku-4-5-…-v1:0").
_SUFFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-:"
_TEXT_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_./"


def model_ids(vendor: str) -> st.SearchStrategy[str]:
    """Bedrock model IDs of the given family, with/without a regional prefix."""
    return st.builds(
        lambda prefix, suffix: f"{prefix}{vendor}.{suffix}",
        st.sampled_from(REGIONAL_PREFIXES),
        st.text(alphabet=_SUFFIX_ALPHABET, min_size=1, max_size=40),
    )


simple_strings = st.text(alphabet=_TEXT_ALPHABET, min_size=1, max_size=40)

# Ordered pairs of *distinct* vendors — cross-family generation/judge (Req 8.5).
distinct_vendor_pairs = st.sampled_from(
    [(g, j) for g in VENDORS for j in VENDORS if g != j]
)

# Wrong-typed replacement values per field. All survive a YAML round trip
# with their Python type intact; None is excluded because the loader treats
# it as "absent". bool is included for int fields (bool subclasses int and
# must still be rejected) and for str fields.
_WRONG_TYPED = {
    "model_id": st.sampled_from([42, 3.5, True, ["a", "b"], {"k": 1}]),
    "retrieval_top_k": st.sampled_from(["ten", "5", 3.5, True, [1, 2], {"k": 1}]),
    "prompt_version": st.sampled_from([42, 3.5, False, ["v1"], {"k": 1}]),
    "judge_model_id": st.sampled_from([7, 0.25, True, ["x"], {"k": 1}]),
    "dataset_path": st.sampled_from([42, 3.5, True, ["p"], {"k": 1}]),
    "results_dir": st.sampled_from([42, 3.5, False, ["r"], {"k": 1}]),
}


@st.composite
def valid_config_dicts(draw) -> dict:
    """A complete, well-typed config mapping with cross-family judge/generation
    models; optional fields are independently present or absent."""
    gen_vendor, judge_vendor = draw(distinct_vendor_pairs)
    config = {
        "model_id": draw(model_ids(gen_vendor)),
        "retrieval_top_k": draw(st.integers(min_value=1, max_value=100)),
        "prompt_version": draw(simple_strings),
        "judge_model_id": draw(model_ids(judge_vendor)),
    }
    for optional in OPTIONAL_FIELDS:
        if draw(st.booleans()):
            config[optional] = draw(simple_strings)
    return config


def _write_config(tmp_dir: str, raw: dict) -> Path:
    path = Path(tmp_dir) / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _load(raw: dict) -> EvalConfig:
    with tempfile.TemporaryDirectory() as tmp_dir:
        return load_config(_write_config(tmp_dir, raw))


def _load_expecting_error(raw: dict) -> EvalConfigError:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = _write_config(tmp_dir, raw)
        with pytest.raises(EvalConfigError) as excinfo:
            load_config(path)
    return excinfo.value


class TestProperty18ConfigValidation:
    # deadline=None: each example writes real files; filesystem latency
    # jitter must not fail otherwise-passing examples.
    @settings(max_examples=100, deadline=None)
    @given(raw=valid_config_dicts())
    def test_valid_cross_family_config_loads_with_exact_values(self, raw):
        """Any complete, well-typed config whose judge and generation models
        come from different families loads successfully and carries the exact
        configured values, with dataclass defaults for absent optional fields
        (Req 6.2, 8.5)."""
        config = _load(raw)
        assert config.model_id == raw["model_id"]
        assert config.retrieval_top_k == raw["retrieval_top_k"]
        assert config.prompt_version == raw["prompt_version"]
        assert config.judge_model_id == raw["judge_model_id"]
        assert config.dataset_path == raw.get(
            "dataset_path", EvalConfig.__dataclass_fields__["dataset_path"].default
        )
        assert config.results_dir == raw.get(
            "results_dir", EvalConfig.__dataclass_fields__["results_dir"].default
        )

    @settings(max_examples=100, deadline=None)
    @given(
        raw=valid_config_dicts(),
        field=st.sampled_from(REQUIRED_FIELDS),
        variant=st.sampled_from(["removed", "null"]),
    )
    def test_missing_required_field_aborts_naming_the_parameter(
        self, raw, field, variant
    ):
        """Removing (or nulling) any required parameter makes load_config
        abort with an EvalConfigError whose message names that parameter,
        before any item could run (Req 6.8)."""
        if variant == "removed":
            del raw[field]
        else:
            raw[field] = None
        error = _load_expecting_error(raw)
        assert field in str(error), (
            f"error message {str(error)!r} does not name the missing "
            f"parameter {field!r}"
        )

    @settings(max_examples=100, deadline=None)
    @given(raw=valid_config_dicts(), data=st.data())
    def test_wrongly_typed_field_aborts_naming_the_parameter(self, raw, data):
        """Replacing any config field with a wrongly-typed value makes
        load_config abort with an EvalConfigError naming that parameter
        (Req 6.8)."""
        candidates = [f for f in (*REQUIRED_FIELDS, *OPTIONAL_FIELDS) if f in raw]
        field = data.draw(st.sampled_from(candidates), label="field")
        raw[field] = data.draw(_WRONG_TYPED[field], label="wrong_value")
        error = _load_expecting_error(raw)
        assert field in str(error), (
            f"error message {str(error)!r} does not name the wrongly-typed "
            f"parameter {field!r}"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        raw=valid_config_dicts(),
        vendor=st.sampled_from(VENDORS),
        data=st.data(),
    )
    def test_same_family_judge_aborts_naming_the_conflict(self, raw, vendor, data):
        """When judge and generation models share a model family — across
        arbitrary regional-prefix combinations — load_config aborts with an
        EvalConfigError naming both model IDs and the shared family
        (Req 8.5, 8.8)."""
        raw["model_id"] = data.draw(model_ids(vendor), label="model_id")
        raw["judge_model_id"] = data.draw(model_ids(vendor), label="judge_model_id")
        error = _load_expecting_error(raw)
        message = str(error)
        assert raw["model_id"] in message
        assert raw["judge_model_id"] in message
        assert vendor in message
