"""Assertion specifications.

These models are **pure data**: they describe *what* to check, never *how*.
The check itself lives in :mod:`conversat.assertions`, which dispatches on the
``type`` discriminator. That keeps this module free of engine imports and lets
users register their own strategies without touching the models.

Two authoring styles are supported::

    - contains: "hello"                       # shorthand
    - type: contains
      value: "hello"
      case_sensitive: false
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SerializeAsAny

JsonOp = Literal[
    "exists",
    "missing",
    "eq",
    "ne",
    "contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "len_eq",
    "len_gt",
    "len_lt",
    "is_true",
    "is_false",
]


class AssertionBase(BaseModel):
    """Common fields for every assertion."""

    model_config = ConfigDict(extra="forbid")

    type: str
    description: str | None = Field(default=None, description="Shown in reports instead of defaults")
    ignore_case: bool = Field(default=False, description="Case-insensitive text comparison")

    def label(self) -> str:
        return self.description or self.describe()

    def describe(self) -> str:
        """Compact human readable description, e.g. ``contains 'hello'``."""
        return self.type


# --------------------------------------------------------------------------- #
# text assertions
# --------------------------------------------------------------------------- #
class EqualsAssertion(AssertionBase):
    type: Literal["equals"] = "equals"
    value: str

    def describe(self) -> str:
        return f"equals {self.value!r}"


class IEqualsAssertion(AssertionBase):
    type: Literal["iequals"] = "iequals"
    value: str

    def describe(self) -> str:
        return f"equals (ignore case) {self.value!r}"


class ContainsAssertion(AssertionBase):
    type: Literal["contains"] = "contains"
    value: str

    def describe(self) -> str:
        return f"contains {self.value!r}"


class NotContainsAssertion(AssertionBase):
    type: Literal["not_contains"] = "not_contains"
    value: str

    def describe(self) -> str:
        return f"does not contain {self.value!r}"


class ContainsAnyAssertion(AssertionBase):
    type: Literal["contains_any"] = "contains_any"
    values: list[str] = Field(min_length=1)

    def describe(self) -> str:
        return f"contains any of {self.values!r}"


class ContainsAllAssertion(AssertionBase):
    type: Literal["contains_all"] = "contains_all"
    values: list[str] = Field(min_length=1)

    def describe(self) -> str:
        return f"contains all of {self.values!r}"


class StartsWithAssertion(AssertionBase):
    type: Literal["starts_with"] = "starts_with"
    value: str

    def describe(self) -> str:
        return f"starts with {self.value!r}"


class EndsWithAssertion(AssertionBase):
    type: Literal["ends_with"] = "ends_with"
    value: str

    def describe(self) -> str:
        return f"ends with {self.value!r}"


class MatchesAssertion(AssertionBase):
    type: Literal["matches"] = "matches"
    pattern: str = Field(description="Regular expression, searched with re.search")

    def describe(self) -> str:
        return f"matches /{self.pattern}/"


class MinLengthAssertion(AssertionBase):
    type: Literal["min_length"] = "min_length"
    value: int = Field(ge=0)

    def describe(self) -> str:
        return f"reply length >= {self.value}"


class MaxLengthAssertion(AssertionBase):
    type: Literal["max_length"] = "max_length"
    value: int = Field(ge=0)

    def describe(self) -> str:
        return f"reply length <= {self.value}"


class NotEmptyAssertion(AssertionBase):
    type: Literal["not_empty"] = "not_empty"

    def describe(self) -> str:
        return "reply is not empty"


class IsEmptyAssertion(AssertionBase):
    type: Literal["is_empty"] = "is_empty"

    def describe(self) -> str:
        return "reply is empty"


class OneOfAssertion(AssertionBase):
    type: Literal["one_of"] = "one_of"
    values: list[str] = Field(min_length=1)

    def describe(self) -> str:
        return f"reply is one of {self.values!r}"


class NoneOfAssertion(AssertionBase):
    type: Literal["none_of"] = "none_of"
    values: list[str] = Field(min_length=1)

    def describe(self) -> str:
        return f"reply is none of {self.values!r}"


class SimilarToAssertion(AssertionBase):
    type: Literal["similar_to"] = "similar_to"
    value: str
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    def describe(self) -> str:
        return f"similar to {self.value!r} (>= {self.threshold:.2f})"


# --------------------------------------------------------------------------- #
# structural assertions
# --------------------------------------------------------------------------- #
class JsonPathAssertion(AssertionBase):
    type: Literal["json_path"] = "json_path"
    path: str = Field(default="", description="Dotted path, e.g. data.reply or items[0].id")
    op: JsonOp = "exists"
    value: Any = None

    def describe(self) -> str:
        target = self.path or "<root>"
        if self.op == "exists":
            return f"json path {target!r} exists"
        if self.op == "missing":
            return f"json path {target!r} is absent"
        return f"json path {target!r} {self.op} {self.value!r}"


class ResponseTimeUnderAssertion(AssertionBase):
    type: Literal["response_time_under"] = "response_time_under"
    value: float = Field(gt=0, description="Maximum acceptable latency in milliseconds")

    def describe(self) -> str:
        return f"responds in under {self.value:g}ms"


class ErrorAssertion(AssertionBase):
    type: Literal["no_error"] = "no_error"
    expect_error: bool = Field(default=False, description="Assert that an error *did* occur")

    def describe(self) -> str:
        return "reply is not an error" if not self.expect_error else "reply is an error"


# --------------------------------------------------------------------------- #
# composite assertions (recursive on purpose)
# --------------------------------------------------------------------------- #
class AnyOfAssertion(AssertionBase):
    type: Literal["any_of"] = "any_of"
    assertions: list[SerializeAsAny["AssertionSpec"]] = Field(
        default_factory=list, min_length=1
    )

    def describe(self) -> str:
        inner = ", ".join(a.describe() for a in self.assertions)
        return f"any of [{inner}]"


class AllOfAssertion(AssertionBase):
    type: Literal["all_of"] = "all_of"
    assertions: list[SerializeAsAny["AssertionSpec"]] = Field(
        default_factory=list, min_length=1
    )

    def describe(self) -> str:
        inner = ", ".join(a.describe() for a in self.assertions)
        return f"all of [{inner}]"


class NotAssertion(AssertionBase):
    type: Literal["not"] = "not"
    assertion: SerializeAsAny["AssertionSpec"]

    def describe(self) -> str:
        return f"not ({self.assertion.describe()})"


# --------------------------------------------------------------------------- #
# shorthand normalisation
# --------------------------------------------------------------------------- #
_SHORTHAND_ALIASES: dict[str, str] = {
    "eq": "equals",
    "ieq": "iequals",
    "regex": "matches",
    "similar": "similar_to",
    "contains_text": "contains",
    "json": "json_path",
    "latency_under": "response_time_under",
    "max_latency": "response_time_under",
    "response_time": "response_time_under",
    "len_gte": "min_length",
    "len_lte": "max_length",
}

_LIST_FIELDS: dict[str, str] = {
    "contains_any": "values",
    "contains_all": "values",
    "one_of": "values",
    "none_of": "values",
    "all_of": "assertions",
    "any_of": "assertions",
}

#: Strategies that take no value at all: ``- not_empty: true``.
_FLAG_STRATEGIES = frozenset({"not_empty", "is_empty"})


def normalize_assertion(raw: Any) -> Any:
    """Turn shorthand YAML into a canonical assertion payload.

    ``"hello"`` -> ``{"type": "contains", "value": "hello"}`` and
    ``{"regex": "^ok"}`` -> ``{"type": "matches", "pattern": "^ok"}``.
    """
    if isinstance(raw, AssertionBase) or not isinstance(raw, (str, dict)):
        return raw
    if isinstance(raw, str):
        return {"type": "contains", "value": raw}
    if "type" in raw:
        return dict(raw)

    if len(raw) != 1:
        raise ValueError(
            "an assertion must be a string, a single-key mapping (e.g. 'contains: hi') "
            f"or carry an explicit 'type' key; got keys {sorted(map(str, raw))}"
        )

    key, value = next(iter(raw.items()))
    name = _SHORTHAND_ALIASES.get(str(key), str(key))
    base: dict[str, Any] = {"type": name}

    if name in _LIST_FIELDS:
        items = value if isinstance(value, (list, tuple)) else [value]
        base[_LIST_FIELDS[name]] = [normalize_assertion(item) for item in items] if name in {
            "all_of",
            "any_of",
        } else [str(v) for v in items]
        return base

    if name in _FLAG_STRATEGIES:
        return base

    if name == "no_error":
        # ``- no_error: true`` asserts a healthy reply, ``- no_error: false``
        # asserts that the bot failed.
        base["expect_error"] = not bool(value)
        return base

    if name == "matches":
        base["pattern"] = str(value)
        return base

    if name == "similar_to" and isinstance(value, dict):
        base.update(value)
        return base

    if name == "json_path":
        if isinstance(value, dict):
            base.update(value)
        else:
            base["path"] = "" if value in (None, "$", "") else str(value)
        return base

    if name == "not":
        base["assertion"] = value
        return base

    base["value"] = value
    return base


# NOTE: no ``Field(discriminator="type")`` here on purpose -- a tagged union
# would bypass the shorthand normaliser above (pydantic builds the tagged-union
# schema and ignores the BeforeValidator). Every member carries its own
# ``Literal`` type tag, so dispatch is still exact.
#
# NOTE: every field holding an ``AssertionSpec`` wraps it in ``SerializeAsAny``.
# Pydantic otherwise serialises a bare union through the *declared* members'
# schemas, which silently drops each strategy's own field (``values``,
# ``pattern``, ``expect_error``, ...) -- a suite written back to YAML would come
# out empty of assertions.
AssertionSpec = Annotated[
    Union[
        EqualsAssertion,
        IEqualsAssertion,
        ContainsAssertion,
        NotContainsAssertion,
        ContainsAnyAssertion,
        ContainsAllAssertion,
        StartsWithAssertion,
        EndsWithAssertion,
        MatchesAssertion,
        MinLengthAssertion,
        MaxLengthAssertion,
        NotEmptyAssertion,
        IsEmptyAssertion,
        OneOfAssertion,
        NoneOfAssertion,
        SimilarToAssertion,
        JsonPathAssertion,
        ResponseTimeUnderAssertion,
        ErrorAssertion,
        AnyOfAssertion,
        AllOfAssertion,
        NotAssertion,
    ],
    BeforeValidator(normalize_assertion),
]

# Resolve the recursive forward references now that the union exists.
AnyOfAssertion.model_rebuild()
AllOfAssertion.model_rebuild()
NotAssertion.model_rebuild()

_adapter: Any = None
_item_adapter: Any = None


def assertion_adapter() -> Any:
    """Return (and memoise) a ``TypeAdapter`` for ``list[AssertionSpec]``."""
    global _adapter
    if _adapter is None:
        from pydantic import TypeAdapter

        _adapter = TypeAdapter(list[AssertionSpec])
    return _adapter


def assertion_item_adapter() -> Any:
    """Return (and memoise) a ``TypeAdapter`` for a single assertion."""
    global _item_adapter
    if _item_adapter is None:
        from pydantic import TypeAdapter

        _item_adapter = TypeAdapter(AssertionSpec)
    return _item_adapter


def parse_assertions(raw: Any) -> list[AssertionBase]:
    """Validate a list (or a single shorthand item) into assertion models."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return list(assertion_adapter().validate_python(items))


__all__ = [
    "AllOfAssertion",
    "AnyOfAssertion",
    "AssertionBase",
    "AssertionSpec",
    "ContainsAllAssertion",
    "ContainsAnyAssertion",
    "ContainsAssertion",
    "EndsWithAssertion",
    "EqualsAssertion",
    "ErrorAssertion",
    "IEqualsAssertion",
    "IsEmptyAssertion",
    "JsonOp",
    "JsonPathAssertion",
    "MatchesAssertion",
    "MaxLengthAssertion",
    "MinLengthAssertion",
    "NoneOfAssertion",
    "NotAssertion",
    "NotContainsAssertion",
    "NotEmptyAssertion",
    "OneOfAssertion",
    "ResponseTimeUnderAssertion",
    "SimilarToAssertion",
    "StartsWithAssertion",
    "assertion_adapter",
    "assertion_item_adapter",
    "normalize_assertion",
    "parse_assertions",
]
