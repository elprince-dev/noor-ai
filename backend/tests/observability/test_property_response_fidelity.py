"""Property 5: Response assembly fidelity (Task 1.5).

*For any* stream of generated tokens and token-usage payload, the Trace's
response field equals the exact concatenation of all streamed tokens, and
the recorded final prompt and input/output token counts equal the values
supplied by the generation step.

Validates: Requirements 2.3.

Pure in-memory: exercises `TraceContext` recording methods and
`build_trace()` directly — no AWS, no monkeypatching.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.models import CostEstimate
from src.observability.trace_context import TraceContext

NOT_COMPUTED = CostEstimate(computed=False, reason="test")

# Text covering Arabic script, Latin, digits, whitespace, punctuation, and
# astral-plane characters — the alphabets a real prompt/response stream mixes.
_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # printable ASCII
        st.characters(),  # anything else Unicode
    ),
)

# A streamed response: any sequence of token chunks (possibly empty strings).
_token_stream = st.lists(_text, min_size=0, max_size=30)

# One or more prompts recorded over the request (agent loop re-prompts after
# tool results) — last one wins.
_prompts = st.lists(_text, min_size=1, max_size=5)

# Token-usage payload: each count independently available or not.
_maybe_count = st.one_of(st.none(), st.integers(min_value=0, max_value=10_000_000))


def make_ctx() -> TraceContext:
    return TraceContext(query="q", session_id="sess", model_id="test-model")


class TestResponseAssemblyFidelity:
    @settings(max_examples=100)
    @given(tokens=_token_stream, prompts=_prompts, usage=st.tuples(_maybe_count, _maybe_count))
    def test_trace_carries_response_prompt_and_usage_faithfully(
        self, tokens: list[str], prompts: list[str], usage: tuple[int | None, int | None]
    ):
        """The built Trace reproduces exactly what the generation step supplied
        (Req 2.3): concatenated stream as response, last prompt, given counts."""
        ctx = make_ctx()

        for prompt in prompts:
            ctx.record_prompt(prompt)

        # Simulate stream assembly: the pipeline concatenates every streamed
        # token and records the complete answer once the stream ends.
        assembled = ""
        for token in tokens:
            assembled += token
        ctx.record_response(assembled)

        input_tokens, output_tokens = usage
        ctx.record_usage(input_tokens, output_tokens)

        trace = ctx.build_trace(NOT_COMPUTED)

        # Response equals the exact concatenation of all streamed tokens.
        assert trace.response == "".join(tokens)
        # Final prompt is last-wins.
        assert trace.final_prompt == prompts[-1]
        # Token counts equal the supplied values; None stays None.
        assert trace.input_tokens == input_tokens
        assert trace.output_tokens == output_tokens

    @settings(max_examples=100)
    @given(tokens=_token_stream)
    def test_response_survives_json_round_trip_unchanged(self, tokens: list[str]):
        """Serialization via to_dict preserves the response byte-for-byte —
        Arabic and unusual characters included (Req 2.3)."""
        ctx = make_ctx()
        answer = "".join(tokens)
        ctx.record_response(answer)
        trace = ctx.build_trace(NOT_COMPUTED)
        assert trace.to_dict()["response"] == answer

    @settings(max_examples=100)
    @given(prompts=st.lists(_text, min_size=2, max_size=6))
    def test_record_prompt_overwrites_never_appends(self, prompts: list[str]):
        """Each record_prompt replaces the previous one entirely; earlier
        prompts leave no residue in the final Trace (Req 2.3)."""
        ctx = make_ctx()
        for prompt in prompts:
            ctx.record_prompt(prompt)
        assert ctx.build_trace(NOT_COMPUTED).final_prompt == prompts[-1]

    @settings(max_examples=100)
    @given(input_tokens=_maybe_count, output_tokens=_maybe_count)
    def test_usage_none_values_stay_none_independently(
        self, input_tokens: int | None, output_tokens: int | None
    ):
        """Each count is recorded independently; unavailable (None) counts are
        never substituted with zero or any other value (Req 2.3, 2.8)."""
        ctx = make_ctx()
        ctx.record_usage(input_tokens, output_tokens)
        trace = ctx.build_trace(NOT_COMPUTED)
        assert trace.input_tokens == input_tokens
        assert trace.output_tokens == output_tokens
