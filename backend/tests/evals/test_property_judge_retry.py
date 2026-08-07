"""Property 23: Judge retry discipline (design.md Correctness Properties).

*For any* scripted sequence of judge behaviors (success, failure,
unparseable output), each scoring call is retried at most exactly once; a
verdict is recorded as an evaluation error (distinct from pass and fail)
only when both attempts fail; and scoring always continues through the
remaining metrics and items.

**Validates: Requirements 8.6**

Pure in-memory Hypothesis test — no AWS calls. `GenerationScorer` is driven
with a `ScriptedJudge` fake whose behavior is scripted per (item, rubric)
call: succeed with a verdict, raise `VerdictParseError` (unparseable
output), or raise a transport error. The judge records every invocation so
the test can assert, per rubric:

(a) first-attempt success ⇒ exactly 1 judge invocation, the verdict recorded;
(b) fail-then-succeed ⇒ exactly 2 invocations, the *retry's* verdict and
    rationale recorded;
(c) fail-fail ⇒ exactly 2 invocations (never a third), outcome "error"
    (distinct from pass/fail) with a rationale carrying the final exception;
(d) an error on one rubric never prevents the remaining rubrics from being
    scored — every expected rubric has an outcome.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.judge import Verdict, VerdictParseError
from evals.metrics.generation import ERROR, GenerationScorer
from tests.evals.test_property_rubric_selection import (
    any_text,
    expected_rubric_names,
    golden_items,
    retrieved_chunks,
)


class ScriptedTransportError(Exception):
    """Stands in for a boto3/transport failure raised by the judge."""


# -- scripted behaviors --------------------------------------------------------
#
# A scenario describes what the judge does across the attempts for one
# (item, rubric) pair:
#   ("first_try", verdict)                 — attempt 1 succeeds
#   ("retry_succeeds", kind, verdict)      — attempt 1 raises `kind`, attempt 2 succeeds
#   ("both_fail", kind1, kind2)            — both attempts raise
# where kind ∈ {"parse", "transport"} and verdict ∈ {"pass", "fail"}.

FAILURE_KINDS = ("parse", "transport")
VERDICTS = ("pass", "fail")

scenarios = st.one_of(
    st.tuples(st.just("first_try"), st.sampled_from(VERDICTS)),
    st.tuples(
        st.just("retry_succeeds"),
        st.sampled_from(FAILURE_KINDS),
        st.sampled_from(VERDICTS),
    ),
    st.tuples(
        st.just("both_fail"),
        st.sampled_from(FAILURE_KINDS),
        st.sampled_from(FAILURE_KINDS),
    ),
)


def _raise_for(kind: str, rubric_name: str, attempt: int) -> Exception:
    message = f"scripted {kind} failure {rubric_name} attempt {attempt}"
    if kind == "parse":
        return VerdictParseError(message)
    return ScriptedTransportError(message)


def _behaviors_for(rubric_name: str, scenario: tuple) -> list:
    """Expand a scenario into the per-call behavior queue for one rubric.

    Each behavior is either an Exception to raise or a Verdict to return;
    rationales are tagged with the attempt number so the test can verify
    *which* attempt's verdict was recorded.
    """
    mode = scenario[0]
    if mode == "first_try":
        return [Verdict(verdict=scenario[1], rationale=f"attempt 1 {rubric_name}")]
    if mode == "retry_succeeds":
        return [
            _raise_for(scenario[1], rubric_name, 1),
            Verdict(verdict=scenario[2], rationale=f"attempt 2 {rubric_name}"),
        ]
    return [
        _raise_for(scenario[1], rubric_name, 1),
        _raise_for(scenario[2], rubric_name, 2),
    ]


EXPECTED_CALLS = {"first_try": 1, "retry_succeeds": 2, "both_fail": 2}


class ScriptedJudge:
    """Scripted `Judge` fake: per-rubric behavior queues + call recording.

    Each `score` call pops the next scripted behavior for that rubric —
    raising it if it is an exception, returning it if it is a Verdict.
    Behavior queues may carry extra trailing entries (see the padded test)
    so an over-eager third attempt would *succeed* rather than crash,
    making the exactly-two-attempts assertions load-bearing.
    """

    def __init__(self, scripts: dict[str, list]) -> None:
        self._scripts = {name: list(behaviors) for name, behaviors in scripts.items()}
        self.calls: list[tuple[str, str]] = []  # (rubric name, item id)

    def calls_for(self, rubric_name: str) -> int:
        return sum(1 for name, _ in self.calls if name == rubric_name)

    def score(self, rubric, item, answer, retrieved) -> Verdict:
        self.calls.append((rubric.name, item.id))
        behavior = self._scripts[rubric.name].pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


class TestProperty23JudgeRetryDiscipline:
    @settings(max_examples=100)
    @given(
        item=golden_items(),
        answer=any_text,
        retrieved=retrieved_chunks,
        data=st.data(),
    )
    def test_each_rubric_gets_at_most_one_retry_and_errors_never_halt_scoring(
        self, item, answer, retrieved, data
    ):
        """For any item and any scripted behavior sequence per rubric:
        success ⇒ 1 call; fail-then-succeed ⇒ 2 calls with the retry's
        verdict recorded; fail-fail ⇒ 2 calls and an "error" outcome
        carrying the final exception; and every expected rubric is scored
        regardless of errors on the others (Req 8.6)."""
        expected = expected_rubric_names(item)
        scripted = {
            name: data.draw(scenarios, label=f"scenario[{name}]") for name in expected
        }
        judge = ScriptedJudge(
            {name: _behaviors_for(name, scenario) for name, scenario in scripted.items()}
        )
        scorer = GenerationScorer(judge)

        result = scorer.score_item(item, answer, retrieved)

        # (d) Every expected rubric has an outcome, in rubric order — an
        # error on one rubric never prevents scoring the remaining ones.
        assert result.computed is True
        assert tuple(outcome.rubric for outcome in result.outcomes) == expected
        assert all(item_id == item.id for _, item_id in judge.calls)

        for outcome in result.outcomes:
            scenario = scripted[outcome.rubric]
            mode = scenario[0]

            # Exact invocation counts: never more than one retry.
            assert judge.calls_for(outcome.rubric) == EXPECTED_CALLS[mode]

            if mode == "first_try":
                # (a) One call; the first attempt's verdict is recorded.
                assert outcome.outcome == scenario[1]
                assert outcome.rationale == f"attempt 1 {outcome.rubric}"
            elif mode == "retry_succeeds":
                # (b) Two calls; the *retry's* verdict is recorded.
                assert outcome.outcome == scenario[2]
                assert outcome.rationale == f"attempt 2 {outcome.rubric}"
            else:  # both_fail
                # (c) Outcome is "error" — distinct from pass and fail —
                # and the rationale carries the final (second) exception.
                assert outcome.outcome == ERROR
                assert outcome.outcome not in VERDICTS
                second_kind = scenario[2]
                expected_type = (
                    "VerdictParseError"
                    if second_kind == "parse"
                    else "ScriptedTransportError"
                )
                assert expected_type in outcome.rationale
                assert (
                    f"scripted {second_kind} failure {outcome.rubric} attempt 2"
                    in outcome.rationale
                )

    @settings(max_examples=100)
    @given(
        item=golden_items(),
        answer=any_text,
        retrieved=retrieved_chunks,
        first_kind=st.sampled_from(FAILURE_KINDS),
        second_kind=st.sampled_from(FAILURE_KINDS),
    )
    def test_never_a_third_attempt_even_when_it_would_succeed(
        self, item, answer, retrieved, first_kind, second_kind
    ):
        """When both attempts fail for every rubric, the scorer never makes
        a third call — even though the script has a would-succeed verdict
        waiting as call 3 — and each outcome is "error" (Req 8.6)."""
        expected = expected_rubric_names(item)
        judge = ScriptedJudge(
            {
                name: [
                    _raise_for(first_kind, name, 1),
                    _raise_for(second_kind, name, 2),
                    # Bait: a third attempt would succeed and flip the
                    # outcome to "pass"; the assertions below prove it is
                    # never consumed.
                    Verdict(verdict="pass", rationale=f"attempt 3 {name}"),
                ]
                for name in expected
            }
        )
        scorer = GenerationScorer(judge)

        result = scorer.score_item(item, answer, retrieved)

        assert tuple(outcome.rubric for outcome in result.outcomes) == expected
        for outcome in result.outcomes:
            assert judge.calls_for(outcome.rubric) == 2
            assert outcome.outcome == ERROR
