"""Suite definitions: connectors, turns, cases and suites."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializeAsAny,
    model_validator,
)

from conversat.errors import ConfigError
from conversat.models.assertion import AssertionBase, parse_assertions

TagList = Annotated[list[str], BeforeValidator(lambda v: [str(x) for x in v] if v else [])]
# ``SerializeAsAny`` keeps each strategy's own field (``value``, ``values``,
# ``pattern``, ...) when a suite is dumped back to YAML or JSON. Without it the
# declared base class wins and every assertion serialises to just its type tag.
Expectations = Annotated[list[SerializeAsAny[AssertionBase]], BeforeValidator(parse_assertions)]

_TAG_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class ConnectorConfig(BaseModel):
    """Which bot to talk to, plus the connector-specific settings.

    ``config`` is validated by the connector itself (see
    :mod:`conversat.connectors`), which keeps this model connector-agnostic.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="Connector name, e.g. http / websocket / web / echo")
    config: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, description="Label shown in reports")

    @property
    def label(self) -> str:
        return self.name or self.type

    def merged_with(self, override: dict[str, Any]) -> ConnectorConfig:
        """Return a copy with ``override`` merged into ``config``."""
        return self.model_copy(update={"config": {**self.config, **override}})


#: ``retry_on`` values understood by :class:`RetryPolicy`, mapped to the
#: :class:`~conversat.models.report.TurnStatus` values they cover.
#: ``timeout`` is a flavour of ``error``; ``failed`` is an alias of
#: ``failed_assertion``.
_RETRY_TRIGGERS: dict[str, set[str]] = {
    "error": {"error"},
    "timeout": {"error"},
    "failed": {"failed"},
    "failed_assertion": {"failed"},
}


class RetryPolicy(BaseModel):
    """How (and whether) a failing turn is retried."""

    model_config = ConfigDict(extra="forbid")

    attempts: int = Field(default=1, ge=1, le=10)
    delay: float = Field(default=0.0, ge=0, description="Seconds to wait between attempts")
    backoff: Literal["none", "fixed", "linear", "exponential"] = "fixed"
    retry_on: list[Literal["error", "timeout", "failed", "failed_assertion"]] = Field(
        default_factory=lambda: ["error", "timeout"]
    )

    def delay_for(self, attempt: int) -> float:
        """Delay before ``attempt`` (1-based; the first attempt never waits)."""
        if attempt <= 1 or self.delay <= 0:
            return 0.0
        if self.backoff == "none":
            return 0.0
        if self.backoff == "fixed":
            return self.delay
        if self.backoff == "linear":
            return self.delay * (attempt - 1)
        return self.delay * (2 ** (attempt - 2))

    def should_retry(self, status: str) -> bool:
        """True when a turn that ended in ``status`` is worth retrying."""
        if self.attempts <= 1:
            return False
        return any(status in _RETRY_TRIGGERS.get(trigger, set()) for trigger in self.retry_on)


class Turn(BaseModel):
    """One user message plus the assertions expected on the reply."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    send: str | None = Field(default=None, description="Message to send to the bot (templated)")
    payload: dict[str, Any] | None = Field(
        default=None, description="Connector-specific fields (e.g. web input selectors)"
    )
    expect: Expectations = Field(default_factory=list)
    name: str | None = None
    timeout: float | None = Field(default=None, gt=0)
    retry: RetryPolicy | None = None
    clear_context: bool = Field(default=False, description="Reset connector history before sending")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_payload(self) -> Turn:
        if self.send is None and not self.payload:
            raise ValueError("a turn needs either 'send' (message text) or 'payload' (extra fields)")
        return self

    @property
    def label(self) -> str:
        return self.name or (self.send or "<payload turn>")


class TestCase(BaseModel):
    """A named, multi-turn conversation scenario."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1)
    description: str | None = None
    tags: TagList = Field(default_factory=list)
    setup: list[Turn] = Field(default_factory=list, description="Turns executed before the steps")
    steps: list[Turn] = Field(default_factory=list, alias="turns")
    variables: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = Field(default=None, gt=0)
    retry: RetryPolicy | None = None
    connector: ConnectorConfig | None = Field(default=None, description="Overrides the suite connector")
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_steps(self) -> TestCase:
        if not self.steps:
            raise ValueError(f"case {self.name!r} has no steps to run")
        return self

    def all_turns(self) -> list[Turn]:
        return [*self.setup, *self.steps]

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def matches(self, *, include: set[str] | None = None, exclude: set[str] | None = None) -> bool:
        if not self.enabled:
            return False
        if include and not (include & set(self.tags)):
            return False
        if exclude and (exclude & set(self.tags)):
            return False
        return True


class SuiteDefaults(BaseModel):
    """Values inherited by every case unless overridden."""

    model_config = ConfigDict(extra="forbid")

    timeout: float | None = Field(default=None, gt=0)
    retry: RetryPolicy | None = None
    tags: TagList = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)


class TestSuite(BaseModel):
    """A collection of cases executed against one connector."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1)
    description: str | None = None
    connector: ConnectorConfig
    cases: list[TestCase] = Field(default_factory=list)
    defaults: SuiteDefaults = Field(default_factory=SuiteDefaults)
    variables: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_cases(self) -> TestSuite:
        if not self.cases:
            raise ValueError(f"suite {self.name!r} has no cases")
        seen: set[str] = set()
        for case in self.cases:
            if case.name in seen:
                raise ValueError(f"duplicate case name {case.name!r} in suite {self.name!r}")
            seen.add(case.name)
            for tag in [*case.tags, *self.defaults.tags]:
                if not _TAG_RE.match(tag):
                    raise ValueError(
                        f"invalid tag {tag!r} in case {case.name!r}; "
                        "use letters, digits and _ . : - (max 64 chars)"
                    )
        return self

    # -- selection -------------------------------------------------------- #
    def select(
        self,
        *,
        include_tags: set[str] | None = None,
        exclude_tags: set[str] | None = None,
        names: set[str] | None = None,
        name_pattern: str | None = None,
    ) -> list[TestCase]:
        """Filter cases by tags, exact names and/or a regex over the name."""
        pattern = re.compile(name_pattern) if name_pattern else None
        selected = []
        for case in self.cases:
            tags = set(case.tags) | set(self.defaults.tags)
            if include_tags and not (include_tags & tags):
                continue
            if exclude_tags and (exclude_tags & tags):
                continue
            if names and case.name not in names:
                continue
            if pattern and not pattern.search(case.name):
                continue
            selected.append(case)
        return selected

    def effective_tags(self, case: TestCase) -> list[str]:
        return sorted(set(case.tags) | set(self.defaults.tags))

    # -- inheritance ------------------------------------------------------ #
    def resolve_case(self, case: TestCase) -> TestCase:
        """Apply suite + default inheritance to a case (returns a copy)."""
        updates: dict[str, Any] = {}
        merged_vars = {**self.variables, **self.defaults.variables, **case.variables}
        if merged_vars != case.variables:
            updates["variables"] = merged_vars
        if case.timeout is None:
            timeout = self.defaults.timeout
            if timeout is not None:
                updates["timeout"] = timeout
        if case.retry is None and self.defaults.retry is not None:
            updates["retry"] = self.defaults.retry
        tags = set(case.tags) | set(self.defaults.tags)
        if tags != set(case.tags):
            updates["tags"] = sorted(tags)
        if case.connector is None and self.connector is not None:
            updates["connector"] = self.connector
        return case.model_copy(update=updates) if updates else case

    def connector_for(self, case: TestCase) -> ConnectorConfig:
        return case.connector or self.connector

    def cases_with_context(self, **filters: Any) -> list[TestCase]:
        return [self.resolve_case(c) for c in self.select(**filters)]

    def connector_spec(self) -> str:
        return f"{self.connector.label}"


def require(value: Any, message: str) -> Any:
    """Tiny helper used by loaders to raise :class:`ConfigError` uniformly."""
    if value is None:
        raise ConfigError(message)
    return value
