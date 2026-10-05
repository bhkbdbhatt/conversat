"""Built-in assertion strategies.

Every handler receives the parsed spec plus an
:class:`~conversat.assertions.base.AssertionContext` and returns an
:class:`~conversat.assertions.base.AssertionResult`. Handlers never raise for
"the assertion failed" -- they only raise for genuinely broken input.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from conversat.assertions.base import AssertionContext, AssertionResult, fail, ok
from conversat.assertions.registry import register
from conversat.models.assertion import (
    AllOfAssertion,
    AnyOfAssertion,  # noqa: F401  (referenced in type hints of _any_of)
    AssertionBase,
    ContainsAllAssertion,
    ContainsAnyAssertion,
    ContainsAssertion,
    EndsWithAssertion,
    EqualsAssertion,
    ErrorAssertion,
    IEqualsAssertion,
    IsEmptyAssertion,
    JsonPathAssertion,
    MatchesAssertion,
    MaxLengthAssertion,
    MinLengthAssertion,
    NoneOfAssertion,
    NotAssertion,
    NotContainsAssertion,
    NotEmptyAssertion,
    OneOfAssertion,
    ResponseTimeUnderAssertion,
    SimilarToAssertion,
    StartsWithAssertion,
)
from conversat.utils import coerce_text, normalize_text

# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


@register("equals")
def _equals(spec: EqualsAssertion, ctx: AssertionContext) -> AssertionResult:
    left, right = ctx.haystack(spec.ignore_case), ctx.needle(spec.value, spec.ignore_case)
    actual = ctx.show(ctx.text)
    if left == right:
        return ok("reply matches exactly", expected=spec.value, actual=actual)
    return fail("reply does not equal the expected text", expected=spec.value, actual=actual)


@register("iequals")
def _iequals(spec: IEqualsAssertion, ctx: AssertionContext) -> AssertionResult:
    left, right = ctx.haystack(True), ctx.needle(spec.value, True)
    actual = ctx.show(ctx.text)
    if left == right:
        return ok("reply matches exactly (ignoring case)", expected=spec.value, actual=actual)
    return fail("reply does not equal the expected text", expected=spec.value, actual=actual)


@register("contains")
def _contains(spec: ContainsAssertion, ctx: AssertionContext) -> AssertionResult:
    needle = ctx.needle(spec.value, spec.ignore_case)
    hay = ctx.haystack(spec.ignore_case)
    actual = ctx.show(ctx.text)
    if needle in hay:
        return ok("reply contains the expected phrase", expected=spec.value, actual=actual)
    return fail("expected phrase not found in reply", expected=spec.value, actual=actual)


@register("not_contains")
def _not_contains(spec: NotContainsAssertion, ctx: AssertionContext) -> AssertionResult:
    needle = ctx.needle(spec.value, spec.ignore_case)
    hay = ctx.haystack(spec.ignore_case)
    actual = ctx.show(ctx.text)
    if needle not in hay:
        return ok("forbidden phrase is absent", expected=spec.value, actual=actual)
    return fail("forbidden phrase found in reply", expected=spec.value, actual=actual)


@register("contains_any")
def _contains_any(spec: ContainsAnyAssertion, ctx: AssertionContext) -> AssertionResult:
    hay = ctx.haystack(spec.ignore_case)
    actual = ctx.show(ctx.text)
    hits = [v for v in spec.values if ctx.needle(v, spec.ignore_case) in hay]
    expected = " | ".join(spec.values)
    if hits:
        return ok(f"found one of the alternatives ({hits[0]!r})", expected=expected, actual=actual)
    return fail("none of the alternatives appear in the reply", expected=expected, actual=actual)


@register("contains_all")
def _contains_all(spec: ContainsAllAssertion, ctx: AssertionContext) -> AssertionResult:
    hay = ctx.haystack(spec.ignore_case)
    actual = ctx.show(ctx.text)
    missing = [v for v in spec.values if ctx.needle(v, spec.ignore_case) not in hay]
    expected = " + ".join(spec.values)
    if not missing:
        return ok("all required phrases present", expected=expected, actual=actual)
    return fail(
        f"missing {len(missing)} phrase(s): {', '.join(repr(m) for m in missing)}",
        expected=expected,
        actual=actual,
    )


@register("starts_with")
def _starts_with(spec: StartsWithAssertion, ctx: AssertionContext) -> AssertionResult:
    text = normalize_text(ctx.text, case_sensitive=not spec.ignore_case, collapse_whitespace=False)
    prefix = ctx.needle(spec.value, spec.ignore_case)
    actual = ctx.show(ctx.text)
    if text.startswith(prefix):
        return ok("reply starts with the expected prefix", expected=spec.value, actual=actual)
    return fail("reply does not start with the expected prefix", expected=spec.value, actual=actual)


@register("ends_with")
def _ends_with(spec: EndsWithAssertion, ctx: AssertionContext) -> AssertionResult:
    text = normalize_text(ctx.text, case_sensitive=not spec.ignore_case, collapse_whitespace=False)
    suffix = ctx.needle(spec.value, spec.ignore_case)
    actual = ctx.show(ctx.text)
    if text.endswith(suffix):
        return ok("reply ends with the expected suffix", expected=spec.value, actual=actual)
    return fail("reply does not end with the expected suffix", expected=spec.value, actual=actual)


@register("matches")
def _matches(spec: MatchesAssertion, ctx: AssertionContext) -> AssertionResult:
    flags = re.IGNORECASE if spec.ignore_case else 0
    text = ctx.text
    try:
        pattern = re.compile(spec.pattern, flags)
    except re.error as exc:
        return fail(f"invalid regular expression: {exc}", expected=spec.pattern)
    actual = ctx.show(ctx.text)
    if pattern.search(text):
        return ok("reply matches the pattern", expected=spec.pattern, actual=actual)
    return fail("reply does not match the pattern", expected=spec.pattern, actual=actual)


@register("min_length")
def _min_length(spec: MinLengthAssertion, ctx: AssertionContext) -> AssertionResult:
    length = len(ctx.text)
    actual = f"{length} chars"
    if length >= spec.value:
        return ok("reply is long enough", expected=f">= {spec.value} chars", actual=actual)
    return fail("reply is shorter than expected", expected=f">= {spec.value} chars", actual=actual)


@register("max_length")
def _max_length(spec: MaxLengthAssertion, ctx: AssertionContext) -> AssertionResult:
    length = len(ctx.text)
    actual = f"{length} chars"
    if length <= spec.value:
        return ok("reply is not too long", expected=f"<= {spec.value} chars", actual=actual)
    return fail("reply is longer than expected", expected=f"<= {spec.value} chars", actual=actual)


@register("not_empty")
def _not_empty(spec: NotEmptyAssertion, ctx: AssertionContext) -> AssertionResult:
    actual = ctx.show(ctx.text) or "<empty>"
    if ctx.text.strip():
        return ok("reply is not empty", actual=actual)
    return fail("bot returned an empty reply", actual=actual)


@register("is_empty")
def _is_empty(spec: IsEmptyAssertion, ctx: AssertionContext) -> AssertionResult:
    actual = ctx.show(ctx.text) or "<empty>"
    if not ctx.text.strip():
        return ok("reply is empty", actual=actual)
    return fail("expected an empty reply", actual=actual)


@register("one_of")
def _one_of(spec: OneOfAssertion, ctx: AssertionContext) -> AssertionResult:
    hay = ctx.haystack(spec.ignore_case)
    actual = ctx.show(ctx.text)
    expected = " | ".join(spec.values)
    if any(ctx.needle(v, spec.ignore_case) == hay for v in spec.values):
        return ok("reply is one of the accepted answers", expected=expected, actual=actual)
    return fail("reply is not one of the accepted answers", expected=expected, actual=actual)


@register("none_of")
def _none_of(spec: NoneOfAssertion, ctx: AssertionContext) -> AssertionResult:
    hay = ctx.haystack(spec.ignore_case)
    actual = ctx.show(ctx.text)
    expected = " | ".join(spec.values)
    if not any(ctx.needle(v, spec.ignore_case) == hay for v in spec.values):
        return ok("reply is not one of the rejected answers", expected=expected, actual=actual)
    return fail("reply matches a rejected answer", expected=expected, actual=actual)


@register("similar_to")
def _similar_to(spec: SimilarToAssertion, ctx: AssertionContext) -> AssertionResult:
    ratio = difflib.SequenceMatcher(None, ctx.haystack(spec.ignore_case), ctx.needle(spec.value, spec.ignore_case)).ratio()
    actual = f"similarity {ratio:.2f}"
    expected = f">= {spec.threshold:.2f} vs {spec.value!r}"
    if ratio >= spec.threshold:
        return ok("reply is close enough to the expected text", expected=expected, actual=actual)
    return fail("reply is too different from the expected text", expected=expected, actual=actual)


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #


def _resolve(payload: Any, path: str) -> tuple[bool, Any]:
    from conversat.utils import extract_by_path

    missing = object()
    value = extract_by_path(payload, path, default=missing)
    return (value is not missing), value


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


@register("json_path")
def _json_path(spec: JsonPathAssertion, ctx: AssertionContext) -> AssertionResult:
    found, value = _resolve(ctx.payload, spec.path)
    actual = ctx.show(value) if found else "<missing>"
    target = spec.path or "<root>"

    if spec.op == "exists":
        return (
            ok(f"json path {target!r} exists", actual=actual)
            if found
            else fail(f"json path {target!r} is missing", expected="present", actual=actual)
        )
    if spec.op == "missing":
        return (
            ok(f"json path {target!r} is absent", actual=actual)
            if not found
            else fail(f"json path {target!r} should be absent", expected="absent", actual=actual)
        )

    if not found:
        return fail(f"json path {target!r} is missing", expected=spec.describe(), actual="<missing>")

    expected_repr = coerce_text(spec.value)
    match = True
    detail = ""

    if spec.op == "eq":
        match = value == spec.value or str(value) == str(spec.value)
        detail = "equal to"
    elif spec.op == "ne":
        match = not (value == spec.value or str(value) == str(spec.value))
        detail = "different from"
    elif spec.op == "contains":
        haystack, needle = coerce_text(value), coerce_text(spec.value)
        match = needle in haystack
        detail = "contains"
    elif spec.op == "not_in" and isinstance(spec.value, (list, tuple, set)):
        options = list(spec.value)
        match = value not in options
        detail = "is not a member of"
    elif spec.op == "in" and not isinstance(spec.value, (list, tuple, set)):
        haystack, needle = normalize_text(coerce_text(value)), normalize_text(coerce_text(spec.value))
        match = needle in haystack
        detail = "contains"
        options = spec.value if isinstance(spec.value, (list, tuple, set)) else [spec.value]
        match = value in options
        detail = "is a member of"
    elif spec.op == "not_in":
        options = spec.value if isinstance(spec.value, (list, tuple, set)) else [spec.value]
        match = value not in options
        detail = "is not a member of"
    elif spec.op == "is_true":
        match = bool(value) is True
        detail = "is true"
    elif spec.op == "is_false":
        match = bool(value) is False
        detail = "is false"
    elif spec.op in {"gt", "gte", "lt", "lte"}:
        left, right = _numeric(value), _numeric(spec.value)
        if left is None or right is None:
            return fail(
                f"cannot compare non-numeric values ({value!r} / {spec.value!r})",
                expected=spec.describe(),
                actual=actual,
            )
        match = {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[spec.op]
        detail = spec.op
    elif spec.op in {"len_eq", "len_gt", "len_lt"}:
        length = len(value) if isinstance(value, (Mapping, Sequence, set, str)) else None
        if length is None:
            return fail("value has no length", expected=spec.describe(), actual=actual)
        target = _numeric(spec.value)
        assert target is not None
        match = {"len_eq": length == target, "len_gt": length > target, "len_lt": length < target}[
            spec.op
        ]
        detail = f"length {spec.op} {target:g}"
    else:  # pragma: no cover - Literal keeps this unreachable
        return fail(f"unsupported json op {spec.op!r}", actual=actual)

    if match:
        return ok(f"json path {target!r} {detail} {expected_repr!r}", actual=actual)
    return fail(f"json path {target!r} is not {detail} {expected_repr!r}", expected=spec.value, actual=actual)


@register("response_time_under")
def _response_time_under(
    spec: ResponseTimeUnderAssertion, ctx: AssertionContext
) -> AssertionResult:
    latency = ctx.response.latency_ms
    if latency is None:
        return ok("no latency recorded (skipped)", expected=f"< {spec.value}ms", actual="n/a")
    actual = f"{latency:.0f}ms"
    if latency <= spec.value:
        return ok("reply arrived within the latency budget", expected=f"<= {spec.value}ms", actual=actual)
    return fail("reply exceeded the latency budget", expected=f"<= {spec.value}ms", actual=actual)


@register("no_error")
def _no_error(spec: ErrorAssertion, ctx: AssertionContext) -> AssertionResult:
    actual = ctx.show(ctx.response.error) if ctx.response.error else ctx.show(ctx.text)
    if spec.expect_error:
        return (
            ok("an error was reported as expected", actual=actual)
            if ctx.response.is_error
            else fail("expected an error but the bot replied", actual=actual)
        )
    return (
        ok("no transport/connector error", actual=actual)
        if not ctx.response.is_error
        else fail(f"connector error: {ctx.response.error}", actual=actual)
    )


# --------------------------------------------------------------------------- #
# composites
# --------------------------------------------------------------------------- #
def _run_child(spec: AssertionBase, ctx: AssertionContext) -> AssertionResult:
    from conversat.assertions.registry import evaluate

    return evaluate(spec, ctx)


@register("all_of")
def _all_of(spec: AllOfAssertion, ctx: AssertionContext) -> AssertionResult:
    failures: list[str] = []
    for child in spec.assertions:
        result = _run_child(child, ctx)
        if not result.passed:
            failures.append(result.message or child.describe())
    if failures:
        return fail("; ".join(failures), expected=spec.describe(), actual=ctx.show(ctx.text))
    return ok("all nested assertions passed", expected=spec.describe())


@register("any_of")
def _any_of(spec: AnyOfAssertion, ctx: AssertionContext) -> AssertionResult:
    details: list[str] = []
    for child in spec.assertions:
        result = _run_child(child, ctx)
        if result.passed:
            return ok(
                f"matched {child.describe()}", expected=spec.describe(), actual=ctx.show(ctx.text)
            )
        details.append(result.message or child.describe())
    return fail(
        f"none of the alternatives matched ({len(details)} tried)",
        expected=spec.describe(),
        actual=ctx.show(ctx.text),
    )


@register("not")
def _not(spec: NotAssertion, ctx: AssertionContext) -> AssertionResult:
    result = _run_child(spec.assertion, ctx)
    if result.passed:
        return fail(
            f"negated assertion unexpectedly matched: {spec.assertion.describe()}",
            expected=f"not ({spec.assertion.describe()})",
            actual=ctx.show(ctx.text),
        )
    return ok(
        f"negated assertion did not match ({result.message})",
        expected=f"not ({spec.assertion.describe()})",
        actual=ctx.show(ctx.text),
    )

