"""Judge_Model boundary: `Judge` protocol + `NovaJudge` (Req 8.1, 8.2, 8.3, 8.4).

This module owns everything that touches the judge model:

- The four discrete pass/fail rubrics (faithfulness, citation accuracy,
  answer relevancy, abstention) as `Rubric` constants, each with the prompt
  criteria mandated by Req 8.1-8.4.
- `build_rubric_prompt(...)` — composes the full judge prompt; every prompt
  ends with the JSON-verdict instruction so the reply is machine-parseable.
- `parse_verdict(text)` — extracts and validates the
  `{"verdict": "pass"|"fail", "rationale": ...}` object, tolerating
  surrounding prose; anything unparseable raises `VerdictParseError`.
- `NovaJudge` — the production adapter: exactly one Bedrock Converse call
  per (item, rubric) with `temperature=0`.

Scoring *policy* (rubric selection per category, retry discipline,
aggregation) deliberately lives in `metrics/generation.py` with the judge
injected, so property tests run against scripted fakes — never AWS.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, Sequence

from evals.dataset import GoldenItem


class VerdictParseError(Exception):
    """The judge reply contained no valid verdict JSON object (Req 8.6)."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """A single discrete judge verdict for one (item, rubric) pair."""

    verdict: str  # "pass" | "fail"
    rationale: str


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A retrieved corpus chunk as presented to the judge: Source_ID + text.

    The judge must see the chunk contents labeled with their Source_IDs to
    verify faithfulness and citation accuracy (Req 8.1, 8.2).
    """

    source_id: str
    text: str


@dataclass(frozen=True, slots=True)
class Rubric:
    """One discrete pass/fail rubric: a name plus the judge-facing criteria.

    `includes_chunks` controls whether the prompt carries the retrieved
    chunks section (needed for faithfulness and citation accuracy).
    """

    name: str
    criteria: str
    includes_chunks: bool


# Every judge prompt ends with this exact instruction (design §judge.py).
JSON_VERDICT_INSTRUCTION = (
    'Respond with only a JSON object: {"verdict": "pass"|"fail", "rationale": "..."}'
)

# -- Rubrics (Req 8.1-8.4) ----------------------------------------------------

FAITHFULNESS = Rubric(
    name="faithfulness",
    criteria=(
        "Rubric: faithfulness. The verdict is 'pass' only if every claim in "
        "the answer is supported by the retrieved chunks provided below. If "
        "any claim in the answer is not supported by the retrieved chunks, "
        "the verdict is 'fail'."
    ),
    includes_chunks=True,
)

CITATION_ACCURACY = Rubric(
    name="citation_accuracy",
    criteria=(
        "Rubric: citation accuracy. The verdict is 'pass' only if the answer "
        "contains at least one cited Source_ID (a Quran verse reference such "
        "as 'Quran 2:255' or a hadith reference such as 'Sahih al-Bukhari 1' "
        "or 'Sahih Muslim 1') AND each cited Source_ID supports the statement "
        "it is attached to, verified against the retrieved chunks provided "
        "below. An answer containing zero cited Source_IDs is always 'fail'. "
        "An answer citing a Source_ID that does not support its attached "
        "statement is 'fail'."
    ),
    includes_chunks=True,
)

ANSWER_RELEVANCY = Rubric(
    name="answer_relevancy",
    criteria=(
        "Rubric: answer relevancy. The verdict is 'pass' only if the answer "
        "addresses the question asked. If the answer is off-topic, answers a "
        "different question, or fails to engage with what was asked, the "
        "verdict is 'fail'."
    ),
    includes_chunks=False,
)

ABSTENTION = Rubric(
    name="abstention",
    criteria=(
        "Rubric: abstention. The verdict is 'pass' only if the answer clearly "
        "declines to answer, stating that no source was found in the corpus "
        "(the Quran, Sahih al-Bukhari, and Sahih Muslim) for this question. "
        "If the answer asserts substantive sourced content instead of "
        "abstaining, the verdict is 'fail'."
    ),
    includes_chunks=False,
)


def build_rubric_prompt(
    rubric: Rubric,
    question: str,
    answer: str,
    retrieved: Sequence[RetrievedChunk],
) -> str:
    """Compose the full judge prompt for one (item, rubric) pair.

    The prompt always ends with `JSON_VERDICT_INSTRUCTION` so the reply can
    be parsed by `parse_verdict`. When the rubric requires it, the retrieved
    chunks are included with their Source_ID labels (Req 8.1, 8.2).
    """
    sections = [
        "You are an impartial evaluation judge for an Islamic Q&A system "
        "that answers questions from the Quran, Sahih al-Bukhari, and "
        "Sahih Muslim.",
        rubric.criteria,
        f"Question:\n{question}",
    ]
    if rubric.includes_chunks:
        chunks_block = "\n\n".join(
            f"[{chunk.source_id}]\n{chunk.text}" for chunk in retrieved
        ) or "(no chunks were retrieved)"
        sections.append(
            "Retrieved chunks (each labeled with its Source_ID):\n" + chunks_block
        )
    sections.append(f"Answer under evaluation:\n{answer}")
    sections.append(JSON_VERDICT_INSTRUCTION)
    return "\n\n".join(sections)


_JSON_DECODER = json.JSONDecoder()


def parse_verdict(text: str) -> Verdict:
    """Extract and validate the verdict JSON object from a judge reply.

    Tolerates surrounding prose: scans every `{` in the text and returns the
    first JSON object whose `verdict` field is exactly "pass" or "fail".
    A missing `rationale` becomes the empty string.

    Raises:
        VerdictParseError: no such object exists anywhere in the text
            (invalid JSON, wrong shape, or a verdict outside {pass, fail}).
    """
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = _JSON_DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        verdict = candidate.get("verdict")
        if verdict not in ("pass", "fail"):
            continue
        rationale = candidate.get("rationale")
        return Verdict(
            verdict=verdict,
            rationale=str(rationale) if rationale is not None else "",
        )
    raise VerdictParseError(
        f"judge reply contains no valid verdict JSON object: {text!r}"
    )


class Judge(Protocol):
    """Scores one generated answer against one rubric (design §judge.py).

    `GenerationScorer` (metrics/generation.py) depends on this protocol so
    property tests can inject scripted fakes; `NovaJudge` is the production
    implementation.
    """

    def score(
        self,
        rubric: Rubric,
        item: GoldenItem,
        answer: str,
        retrieved: Sequence[RetrievedChunk],
    ) -> Verdict:
        """Return the judge's verdict; raises on call failure or unparseable reply."""
        ...


class NovaJudge:
    """Production `Judge`: one Bedrock Converse call per (item, rubric).

    Deterministic scoring via `temperature=0` (Req 8.1-8.4). The judge model
    ID is injected by the composition root (cli.py), which has already
    verified it comes from a different family than the generation model
    (Req 8.5, 8.8). Any transport error or unparseable reply propagates to
    the caller — `GenerationScorer` owns the retry discipline (Req 8.6).
    """

    def __init__(self, model_id: str, client=None) -> None:
        """Args:
        model_id: Bedrock judge model ID (e.g. "us.amazon.nova-pro-v1:0").
        client: optional pre-built bedrock-runtime client (tests); when
            omitted, one is created in the region from src config.
        """
        self._model_id = model_id
        if client is None:
            import boto3

            from src.config import config

            client = boto3.client("bedrock-runtime", region_name=config.bedrock_region)
        self._client = client

    def score(
        self,
        rubric: Rubric,
        item: GoldenItem,
        answer: str,
        retrieved: Sequence[RetrievedChunk],
    ) -> Verdict:
        """Score `answer` for `item` against `rubric` with one Converse call.

        Raises:
            VerdictParseError: the reply contained no valid verdict object.
            Exception: any boto3/transport failure propagates unchanged.
        """
        prompt = build_rubric_prompt(rubric, item.question, answer, retrieved)
        response = self._client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.0},
        )
        blocks = response["output"]["message"]["content"]
        text = "".join(block.get("text", "") for block in blocks)
        return parse_verdict(text)
