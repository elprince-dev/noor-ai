"""Unit tests for `parse_verdict` — realistic Nova judge outputs (Req 8.6).

`parse_verdict` must extract the `{"verdict": "pass"|"fail", "rationale": ...}`
object from a judge reply, tolerating the surrounding prose Nova models often
add, and raise `VerdictParseError` when no valid verdict object exists.
"""
import pytest

from evals.judge import Verdict, VerdictParseError, parse_verdict


# -- Valid replies: clean and prose-wrapped JSON ------------------------------


def test_clean_json():
    text = '{"verdict": "pass", "rationale": "All claims are supported."}'
    assert parse_verdict(text) == Verdict(
        verdict="pass", rationale="All claims are supported."
    )


def test_clean_json_fail_verdict():
    text = '{"verdict": "fail", "rationale": "The answer cites no Source_ID."}'
    assert parse_verdict(text) == Verdict(
        verdict="fail", rationale="The answer cites no Source_ID."
    )


def test_json_preceded_by_prose():
    text = (
        "Here is my assessment of the answer against the faithfulness "
        'rubric: {"verdict": "pass", "rationale": "Every claim traces to '
        'the retrieved chunks."}'
    )
    result = parse_verdict(text)
    assert result.verdict == "pass"
    assert result.rationale == "Every claim traces to the retrieved chunks."


def test_json_followed_by_explanation():
    text = (
        '{"verdict": "fail", "rationale": "The second claim is unsupported."}\n\n'
        "I marked this as fail because the answer asserts a ruling that does "
        "not appear in any retrieved chunk."
    )
    result = parse_verdict(text)
    assert result.verdict == "fail"
    assert result.rationale == "The second claim is unsupported."


def test_json_inside_markdown_code_fence():
    text = (
        "Sure! Here is the verdict:\n\n"
        "```json\n"
        '{"verdict": "pass", "rationale": "The answer addresses the question."}\n'
        "```\n"
    )
    result = parse_verdict(text)
    assert result.verdict == "pass"
    assert result.rationale == "The answer addresses the question."


def test_multiline_pretty_printed_json():
    text = (
        "{\n"
        '    "verdict": "pass",\n'
        '    "rationale": "The citation Quran 49:12 supports the statement."\n'
        "}"
    )
    result = parse_verdict(text)
    assert result.verdict == "pass"
    assert result.rationale == "The citation Quran 49:12 supports the statement."


def test_json_with_extra_fields():
    text = (
        '{"verdict": "fail", "rationale": "Off-topic answer.", '
        '"confidence": 0.93, "rubric": "answer_relevancy"}'
    )
    result = parse_verdict(text)
    assert result.verdict == "fail"
    assert result.rationale == "Off-topic answer."


def test_preceding_non_verdict_json_object_is_skipped():
    text = (
        'First, the claims I identified: {"claims": ["claim one", "claim two"]}. '
        'Final verdict: {"verdict": "pass", "rationale": "Both claims are '
        'supported by [Sahih al-Bukhari 1]."}'
    )
    result = parse_verdict(text)
    assert result.verdict == "pass"
    assert result.rationale == (
        "Both claims are supported by [Sahih al-Bukhari 1]."
    )


def test_rationale_with_arabic_text_and_escaped_quotes():
    text = (
        '{"verdict": "pass", "rationale": "الإجابة مدعومة بالآية '
        '\\"قُلْ هُوَ اللَّهُ أَحَدٌ\\" من سورة الإخلاص."}'
    )
    result = parse_verdict(text)
    assert result.verdict == "pass"
    assert result.rationale == (
        'الإجابة مدعومة بالآية "قُلْ هُوَ اللَّهُ أَحَدٌ" من سورة الإخلاص.'
    )


def test_missing_rationale_becomes_empty_string():
    result = parse_verdict('{"verdict": "pass"}')
    assert result == Verdict(verdict="pass", rationale="")


# -- Invalid replies: VerdictParseError ---------------------------------------


def test_uppercase_verdict_rejected():
    with pytest.raises(VerdictParseError):
        parse_verdict('{"verdict": "PASS", "rationale": "Looks good."}')


def test_out_of_domain_verdict_rejected():
    with pytest.raises(VerdictParseError):
        parse_verdict('{"verdict": "maybe", "rationale": "Hard to say."}')


def test_no_json_at_all():
    with pytest.raises(VerdictParseError):
        parse_verdict(
            "The answer is faithful to the retrieved chunks, so I would "
            "say it passes."
        )


def test_malformed_json():
    with pytest.raises(VerdictParseError):
        parse_verdict('{"verdict": "pass", "rationale": "unterminated')


def test_empty_string():
    with pytest.raises(VerdictParseError):
        parse_verdict("")
