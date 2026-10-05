"""The conversation crawler.

Explores a bot breadth-first within a strict budget (max depth, max turns,
branching factor) and produces a :class:`CrawlReport` containing the
conversation tree, coverage statistics, findings and generated test cases.

Each node gets its **own** connector instance, so sibling branches never share
state -- that keeps the tree correct even for stateful bots.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from conversat.crawler.followups import FollowUpGenerator, default_generator
from conversat.crawler.suggest import build_test_cases, coverage_from, detect_issues
from conversat.engine.base import Connector
from conversat.models.crawler import CrawlConfig, CrawlNode, CrawlReport
from conversat.models.report import TurnStatus, utcnow
from conversat.models.response import BotResponse
from conversat.models.suite import ConnectorConfig
from conversat.utils import normalize_text, stable_hash


@dataclass(slots=True)
class _Item:
    """A queued (or running) crawl work item."""

    request: str
    depth: int
    parent: str | None = None
    key: str = ""
    node_id: str = ""
    children: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CrawlOptions:
    """Runtime knobs for :class:`Crawler`."""

    max_parallel: int = 2
    collect_cases: bool = True
    suite_name: str = "crawled-bot"
    case_name_prefix: str = "crawl"


class Crawler:
    """Bounded, de-duplicating conversation crawler."""

    #: Label/config of the connector under test (set by :func:`crawl`).
    connector_label: str = "unknown"
    connector_config: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        config: CrawlConfig,
        connector_factory: Callable[[ConnectorConfig], Connector],
        *,
        generator: FollowUpGenerator | None = None,
        options: CrawlOptions | None = None,
        on_event: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.connector_factory = connector_factory
        self.generator = generator or default_generator(config.follow_ups)
        self.options = options or CrawlOptions(max_parallel=config.concurrency)
        self.on_event = on_event
        self._seen: set[str] = set()
        self._nodes: dict[str, CrawlNode] = {}
        self._roots: list[str] = []
        self._queue: list[_Item] = []
        self._done = 0
        self._budget_used = 0

    # -- public API ------------------------------------------------------- #
    async def crawl(self) -> CrawlReport:
        """Run the crawl to completion (or until the budget is exhausted)."""
        cfg = self.config
        self._seed()

        if self.on_event is not None:
            self.on_event("crawl_start", cfg)

        await self._process_queue()

        report = self.build_report()
        if self.on_event is not None:
            self.on_event("crawl_end", report)
        return report

    def build_report(self) -> CrawlReport:
        """Assemble a :class:`CrawlReport` from the collected nodes."""
        report = CrawlReport(
            suite=self.options.suite_name,
            started_at=self._started_at,
            finished_at=utcnow(),
            config=self.config,
            connector=self.connector_label,
            connector_config=dict(self.connector_config),
            roots=list(self._roots),
            nodes=list(self._nodes.values()),
        )
        coverage_from(report)
        report.issues = detect_issues(report)
        if self.options.collect_cases:
            report.suggested_cases = build_test_cases(
                report, name_prefix=self.options.case_name_prefix
            )
        return report

    # -- internals -------------------------------------------------------- #
    _started_at: Any = None

    def _seed(self) -> None:
        cfg = self.config
        self._started_at = utcnow()
        for seed in cfg.seeds:
            item = self._enqueue(seed, depth=0, parent=None, force=True)
            if item is not None:
                self._roots.append(item.node_id)

    def _key(self, request: str, depth: int, parent: str | None) -> str:
        normalized = request if self.config.case_sensitive else normalize_text(request)
        return f"{parent or 'root'}::{depth}::{normalized}"

    def _enqueue(self, request: str, *, depth: int, parent: str | None, force: bool = False) -> _Item | None:
        cfg = self.config
        if depth > cfg.max_depth:
            return None
        if len(self._nodes) + len(self._queue) >= cfg.max_turns:
            return None
        key = self._key(request, depth, parent)
        if not force:
            if cfg.dedupe:
                if key in self._seen:
                    return None
                norm = request if cfg.case_sensitive else normalize_text(request)
                if any(norm == seen for seen in self._seen):
                    return None
            self._seen.add(key)
        item = _Item(request=request, depth=depth, parent=parent, key=key)
        item.node_id = f"n{len(self._nodes) + len(self._queue):03d}-{stable_hash(key, length=6)}"
        self._queue.append(item)
        return item

    async def _process_queue(self) -> None:
        cfg = self.config
        while self._queue:
            if self._budget_used >= cfg.max_turns:
                self._queue.clear()
                break
            batch = [self._queue.pop(0) for _ in range(min(self.options.max_parallel, len(self._queue)))]
            remaining = cfg.max_turns - self._budget_used - len(self._nodes)
            if remaining <= 0:
                break
            batch = batch[:remaining]
            self._budget_used += len(batch)

            results = await asyncio.gather(
                *(self._visit(item) for item in batch), return_exceptions=True
            )
            for item, result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    node = CrawlNode(
                        id=item.node_id,
                        depth=item.depth,
                        request=item.request,
                        parent=item.parent,
                        status=TurnStatus.ERROR,
                        error=f"{type(result).__name__}: {result}",
                    )
                    self._register(node)
                    if cfg.stop_on_error:
                        self._queue.clear()
                        return
                    continue
                node = result
                self._register(node)
                if self.on_event is not None:
                    self.on_event("crawl_node", node)
                if cfg.stop_on_error and node.status is TurnStatus.ERROR:
                    self._queue.clear()
                    return
                self._expand(node)

    def _register(self, node: CrawlNode) -> None:
        self._nodes[node.id] = node
        if node.parent:
            parent = self._nodes.get(node.parent)
            if parent is not None and node.id not in parent.children:
                parent.children.append(node.id)

    async def _visit(self, item: _Item) -> CrawlNode:
        cfg = self.config
        node = CrawlNode(id=item.node_id, depth=item.depth, request=item.request, parent=item.parent)
        connector = self.connector_factory()
        try:
            async with connector:
                response = await self._send_with_retry(connector, item.request)
        except Exception as exc:  # noqa: BLE001 - surfaced as a crawl error node
            node.status = TurnStatus.ERROR
            node.error = f"{type(exc).__name__}: {exc}"
            return node

        node.response = response
        node.duration_ms = response.latency_ms or node.duration_ms
        node.status = TurnStatus.ERROR if response.is_error else TurnStatus.PASSED
        node.error = response.error
        return node

    async def _send_with_retry(self, connector: Connector, request: str) -> BotResponse:
        retry = self.config.retry
        attempts = retry.attempts if retry else 1
        last: BotResponse | None = None
        for attempt in range(1, attempts + 1):
            if retry and attempt > 1:
                delay = retry.delay_for(attempt)
                if delay:
                    await asyncio.sleep(delay)
            last = await connector.send(request, timeout=self.config.timeout)
            if not last.is_error:
                return last
        assert last is not None
        return last

    def _expand(self, node: CrawlNode) -> None:
        cfg = self.config
        if node.depth >= cfg.max_depth:
            return
        if node.status is TurnStatus.ERROR:
            return

        reply = node.response.text if node.response else ""
        if any(word.lower() in (node.request or "").lower() for word in cfg.ignore_turns_containing):
            return

        budget = min(cfg.branching, max(cfg.max_turns - len(self._nodes) - len(self._queue), 0))
        if budget <= 0:
            return

        follow_ups = [
            f
            for f in self.generator.generate(node.request, reply, limit=budget)
            if normalize_text(f)
        ]
        seen_here: set[str] = set()
        for follow_up in follow_ups[:budget]:
            norm = normalize_text(follow_up)
            if norm in seen_here:
                continue
            seen_here.add(norm)
            child = self._enqueue(follow_up, depth=node.depth + 1, parent=node.id)
            if child is not None:
                node.follow_ups.append(follow_up)


async def crawl(
    config: CrawlConfig,
    connector_config: ConnectorConfig,
    *,
    generator: FollowUpGenerator | None = None,
    options: CrawlOptions | None = None,
    on_event: Callable[..., Any] | None = None,
) -> CrawlReport:
    """Convenience wrapper around :class:`Crawler`.

    Unlike the test runner, a crawl needs one connector per *branch*, so the
    factory here is zero-argument and creates a fresh connector each call.
    """
    from conversat.connectors.registry import create_connector

    def factory(_config: ConnectorConfig | None = None) -> Connector:
        return create_connector(connector_config)

    crawler = Crawler(config, factory, generator=generator, options=options, on_event=on_event)
    crawler.connector_label = connector_config.label
    crawler.connector_config = dict(connector_config.config)
    return await crawler.crawl()
