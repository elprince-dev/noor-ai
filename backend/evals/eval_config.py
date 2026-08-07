"""Eval_Config loading and validation (Req 6.2, 6.8, 8.5, 8.8).

`load_config(path)` reads a YAML config file and validates presence and type
of every required parameter, aborting with an `EvalConfigError` naming the
offending parameter before any Golden_Item runs (Req 6.8). It also enforces
the judge-independence rule: the Judge_Model must come from a different model
family than the generation model (Req 8.5, 8.8), checked via
`validate_judge_family(config)`.

`model_family(model_id)` extracts the vendor token from a Bedrock model ID,
tolerating cross-region inference prefixes: `us.anthropic.claude-…` →
`anthropic`, `us.amazon.nova-…` → `amazon`.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

# Bedrock cross-region inference profile prefixes (design §eval_config).
REGIONAL_PREFIXES = frozenset({"us", "eu", "apac"})


class EvalConfigError(Exception):
    """The Eval_Config is invalid; the run must abort before any item executes."""


@dataclass(frozen=True)
class EvalConfig:
    """Parameters controlling one Eval_Harness run (Req 6.2)."""

    model_id: str          # generation model
    retrieval_top_k: int
    prompt_version: str    # key into the prompts registry (PROMPT_VERSIONS)
    judge_model_id: str    # must be a different model family (Req 8.5)
    dataset_path: str = "evals/data/golden_dataset.jsonl"
    results_dir: str = "evals/results"


# (name, expected type, required) — bool is excluded from int explicitly below.
_FIELDS: tuple[tuple[str, type, bool], ...] = (
    ("model_id", str, True),
    ("retrieval_top_k", int, True),
    ("prompt_version", str, True),
    ("judge_model_id", str, True),
    ("dataset_path", str, False),
    ("results_dir", str, False),
)


def model_family(model_id: str) -> str:
    """Extract the vendor token from a Bedrock model ID.

    Strips any regional inference prefix (`us.`, `eu.`, `apac.`) then returns
    the segment before the first `.` — e.g. `us.anthropic.claude-haiku-…` →
    `anthropic`, `amazon.nova-pro-v1:0` → `amazon`. An ID with no dot returns
    the whole string.
    """
    segments = model_id.split(".")
    if len(segments) > 1 and segments[0] in REGIONAL_PREFIXES:
        segments = segments[1:]
    return segments[0]


def validate_judge_family(config: EvalConfig) -> None:
    """Abort when the judge and generation models share a family (Req 8.5, 8.8).

    Raises:
        EvalConfigError: naming both model IDs and the shared family.
    """
    generation_family = model_family(config.model_id)
    judge_family = model_family(config.judge_model_id)
    if judge_family == generation_family:
        raise EvalConfigError(
            f"judge_model_id {config.judge_model_id!r} is from the same model "
            f"family ({judge_family!r}) as model_id {config.model_id!r}; the "
            "Judge_Model must come from a different family to avoid "
            "self-preference bias"
        )


def _validate_fields(raw: dict) -> dict:
    """Check presence and type of every field; return kwargs for EvalConfig."""
    kwargs: dict = {}
    for name, expected, required in _FIELDS:
        if name not in raw or raw[name] is None:
            if required:
                raise EvalConfigError(f"missing required config parameter: {name!r}")
            continue  # optional field absent — dataclass default applies
        value = raw[name]
        # bool is a subclass of int; reject it for int-typed fields.
        if not isinstance(value, expected) or isinstance(value, bool) and expected is int:
            raise EvalConfigError(
                f"config parameter {name!r} must be of type {expected.__name__}, "
                f"got {type(value).__name__} ({value!r})"
            )
        kwargs[name] = value
    return kwargs


def load_config(path: str | Path) -> EvalConfig:
    """Load and fully validate the Eval_Config at `path`.

    Raises:
        EvalConfigError: the file is unreadable or not a YAML mapping, a
            required parameter is missing or wrongly typed (naming the
            parameter, Req 6.8), or the judge and generation models share a
            model family (Req 8.5, 8.8). Raised before any item runs.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EvalConfigError(f"config file {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvalConfigError(f"config file {path} must contain a YAML mapping")

    config = EvalConfig(**_validate_fields(raw))
    validate_judge_family(config)
    return config
