"""Playwright E2E web connector: drive a real browser against a chat UI."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from conversat.engine.base import Connector
from conversat.errors import ConnectorError, ConnectorTimeoutError
from conversat.models.response import BotResponse


class WebConfig(BaseModel):
    """Selectors and browser settings for a chat widget."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = Field(default=None, description="Page opened on connect")
    input_selector: str = Field(description="CSS selector of the message input")
    send_selector: str | None = Field(
        default=None, description="Send/submit button; omit to press Enter"
    )
    message_selector: str = Field(
        default="[data-conversat-msg], .bot-message, .message.assistant, .chat-message.bot",
        description="Selector matching bot messages (count grows as the bot replies)",
    )
    clear_selector: str | None = Field(default=None, description="Reset/clear-chat button")
    submit_press: Literal["Enter", "Control+Enter", "Shift+Enter"] = "Enter"
    wait_after_send_ms: int = Field(default=250, ge=0)
    settle_ms: int = Field(default=0, ge=0, description="Extra wait once a reply appeared")
    ready_selector: str | None = Field(default=None, description="Wait for this before sending")
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    timeout: float = Field(default=20.0, gt=0)
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1280, "height": 900})
    ignore_https_errors: bool = False
    screenshot_dir: str | None = Field(default=None, description="Write a screenshot on failure")
    user_agent: str | None = None
    extra_wait_selector: str | None = Field(
        default=None, description="Optional 'typing...' indicator that disappears when done"
    )
    recording_dir: str | None = Field(default=None, description="Record a video of the session")


class WebConnector(Connector):
    """``web`` -- end-to-end browser testing of a chatbot UI.

    Works with any chat UI as long as the input, send control and bot messages
    can be addressed with CSS selectors. Works with Playwright's default
    conversation markers (``data-conversat-msg``) out of the box.
    """

    type_name = "web"
    config_model = WebConfig

    def __init__(self, config: WebConfig | dict[str, Any] | None = None, **kwargs: Any) -> None:
        cfg = config if isinstance(config, WebConfig) else WebConfig.model_validate(config or {})
        super().__init__(cfg)
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._extra = kwargs

    # -- lifecycle -------------------------------------------------------- #
    async def connect(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConnectorError(
                "playwright is not installed; run 'pip install playwright && playwright install chromium'",
                connector=self.type_name,
            ) from exc

        cfg: WebConfig = self.config
        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, cfg.browser)
        self._browser = await launcher.launch(headless=cfg.headless)
        self._context = await self._browser.new_context(
            viewport=cfg.viewport,
            ignore_https_errors=cfg.ignore_https_errors,
            user_agent=cfg.user_agent,
            record_video_dir=cfg.recording_dir,
        )
        self._context.set_default_timeout(cfg.timeout * 1000)
        self._page = await self._context.new_page()
        if cfg.base_url:
            await self._page.goto(cfg.base_url, wait_until="domcontentloaded")
        if cfg.ready_selector:
            await self._page.wait_for_selector(cfg.ready_selector)
        self.metadata["base_url"] = cfg.base_url

    async def close(self) -> None:
        for obj, method in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._playwright, "stop"),
        ):
            if obj is None:
                continue
            try:
                await getattr(obj, method)()
            except Exception:  # noqa: BLE001, S110 - teardown must not raise
                pass
        self._page = self._context = self._browser = self._playwright = None

    async def reset(self) -> None:
        cfg: WebConfig = self.config
        if cfg.clear_selector and self._page is not None:
            await self._page.click(cfg.clear_selector)
            await self._page.wait_for_timeout(200)

    # -- protocol --------------------------------------------------------- #
    async def send(self, text: str, *, timeout: float | None = None) -> BotResponse:
        cfg: WebConfig = self.config
        if self._page is None:
            await self.connect()
        page = self._page
        limit = (timeout or cfg.timeout) * 1000

        try:
            before = await page.locator(cfg.message_selector).count()
            await page.fill(cfg.input_selector, text)
            if cfg.send_selector:
                await page.click(cfg.send_selector)
            else:
                await page.press(cfg.input_selector, cfg.submit_press)
            started = time.perf_counter()

            deadline = time.perf_counter() + limit / 1000
            while time.perf_counter() < deadline:
                current = await page.locator(cfg.message_selector).count()
                if current > before:
                    break
                await asyncio.sleep(0.1)
            else:
                raise ConnectorTimeoutError(
                    f"no new bot message within {limit / 1000:.1f}s", connector=self.type_name
                )

            if cfg.extra_wait_selector:
                try:
                    await page.wait_for_selector(cfg.extra_wait_selector, state="detached", timeout=3000)
                except Exception:  # noqa: BLE001, S110 - indicator is best-effort
                    pass
            if cfg.settle_ms:
                await page.wait_for_timeout(cfg.settle_ms)
            elif cfg.wait_after_send_ms:
                await page.wait_for_timeout(cfg.wait_after_send_ms)

            reply = await self._read_last(page, cfg)
            elapsed = (time.perf_counter() - started) * 1000
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            await self._screenshot("error")
            raise ConnectorError(f"browser error: {exc}", connector=self.type_name) from exc

        return self.record(
            text,
            BotResponse(text=reply, latency_ms=elapsed, metadata={"selector": cfg.message_selector}),
            elapsed,
        )

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    async def _read_last(page: Any, cfg: WebConfig) -> str:
        locator = page.locator(cfg.message_selector)
        count = await locator.count()
        if count == 0:
            return ""
        node = locator.nth(count - 1)
        text = (await node.inner_text()).strip()
        aria = await node.get_attribute("aria-label")
        return aria or text

    async def _screenshot(self, tag: str) -> Path | None:
        cfg: WebConfig = self.config
        if not cfg.screenshot_dir or self._page is None:
            return None
        target = Path(cfg.screenshot_dir)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{tag}-{int(time.time() * 1000)}.png"
        try:
            await self._page.screenshot(path=str(path), full_page=True)
        except Exception:  # noqa: BLE001, S110 - screenshots are best-effort
            return None
        return path
