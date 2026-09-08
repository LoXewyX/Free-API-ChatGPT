import asyncio
import time
from collections.abc import AsyncGenerator

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from free_api_chatgpt.config import (
    CHAT_ID,
    FINAL_CHECK_DELAY,
    HEADLESS,
    INTERNAL_CONTEXT,
    POLL_INTERVAL,
    RESPONSE_TIMEOUT,
    STABLE_TIME,
)


class ChatGPT:
    """Browser-based ChatGPT client."""

    ASSISTANT_SELECTOR = (
        '[data-message-role="assistant"], [data-message-author-role="assistant"]'
    )

    ASSISTANT_CONTENT_SELECTOR = "[data-assistant-markdown]"

    SUBMIT_SELECTOR = "#composer-submit-button, button.wm-composer-submitButton"

    def __init__(
        self,
        page: Page,
        context: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.page = page
        self.context = context if context is not None else INTERNAL_CONTEXT
        self.chat_id = chat_id if chat_id is not None else CHAT_ID
        self.headless = HEADLESS
        self._last_response = ""

    async def composer(self) -> Locator:
        """Return the visible ChatGPT message composer."""
        composer = self.page.get_by_role("textbox").first

        await composer.wait_for(
            state="visible",
            timeout=30_000,
        )

        return composer

    async def submit_button(self) -> Locator:
        """Return the visible ChatGPT submit button."""
        buttons = self.page.locator(self.SUBMIT_SELECTOR)

        for index in range(await buttons.count()):
            button = buttons.nth(index)

            if await button.is_visible():
                return button

        raise PlaywrightTimeoutError("ChatGPT submit button was not found.")

    def assistant_messages(self) -> Locator:
        """Return assistant message elements."""
        return self.page.locator(self.ASSISTANT_SELECTOR)

    async def assistant_count(self) -> int:
        """Return the number of assistant messages."""
        return await self.assistant_messages().count()

    async def latest_assistant_text(self) -> str:
        """Return the latest assistant response text."""
        messages = self.assistant_messages()
        count = await messages.count()

        if count == 0:
            return ""

        message = messages.nth(count - 1)
        content = message.locator(self.ASSISTANT_CONTENT_SELECTOR)

        if await content.count():
            return (await content.inner_text()).strip()

        return (await message.inner_text()).strip()

    async def _response_snapshot(self) -> dict[str, str | int]:
        """Return response text, message count, and generation state."""
        return await self.page.evaluate(
            """
            (selectors) => {
                const messages = document.querySelectorAll(
                    selectors.assistant
                );

                const count = messages.length;

                if (!count) {
                    return {
                        text: "",
                        count: 0,
                        state: "unknown",
                    };
                }

                const message = messages[count - 1];

                const content = message.querySelector(
                    selectors.content
                );

                const text = (
                    content || message
                ).innerText.trim();

                const button = document.querySelector(
                    selectors.submit
                );

                if (!button) {
                    return {
                        text,
                        count,
                        state: "unknown",
                    };
                }

                const stopIcon = button.querySelector(
                    ".wm-composer-stopIcon"
                );

                const sendIcon = button.querySelector(
                    ".wm-composer-sendIcon"
                );

                const visible = element => {
                    if (!element) {
                        return false;
                    }

                    const style =
                        window.getComputedStyle(element);

                    const rect =
                        element.getBoundingClientRect();

                    return (
                        style.display !== "none" &&
                        style.visibility !== "hidden" &&
                        style.opacity !== "0" &&
                        rect.width > 0 &&
                        rect.height > 0
                    );
                };

                let state = "unknown";

                if (visible(stopIcon)) {
                    state = "generating";
                } else if (visible(sendIcon)) {
                    state = "ready";
                }

                return {
                    text,
                    count,
                    state,
                };
            }
            """,
            {
                "assistant": self.ASSISTANT_SELECTOR,
                "content": self.ASSISTANT_CONTENT_SELECTOR,
                "submit": self.SUBMIT_SELECTOR,
            },
        )

    async def generation_state(self) -> str:
        """Return the current generation state."""
        snapshot = await self._response_snapshot()
        return str(snapshot["state"])

    async def accept_cookies(self) -> None:
        """Accept a cookie dialog if one is present."""
        selectors = (
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
            'button:has-text("Allow all")',
            'button:has-text("Agree")',
        )

        for selector in selectors:
            buttons = self.page.locator(selector)

            for index in range(await buttons.count()):
                button = buttons.nth(index)

                if not await button.is_visible():
                    continue

                try:
                    await button.click(timeout=3_000)
                except PlaywrightTimeoutError:
                    pass

                return

    async def initialize_page(self) -> None:
        """Open ChatGPT and wait until the composer is available."""
        url = (
            f"https://chatgpt.com/c/{self.chat_id}"
            if self.chat_id
            else "https://chatgpt.com"
        )

        await self.page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        await self.accept_cookies()
        await self.composer()

    async def initialize_context(self) -> None:
        """Send the configured context message."""
        if self.context:
            await self.ask(self.context)

    async def submit_prompt(self, prompt: str) -> None:
        """Fill and submit a prompt."""
        composer = await self.composer()
        await composer.fill(prompt)

        button = await self.submit_button()
        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            state = await self.generation_state()

            if state == "ready":
                await button.click(timeout=10_000)
                return

            if await button.is_enabled():
                await button.click(timeout=10_000)
                return

            await asyncio.sleep(POLL_INTERVAL)

        raise PlaywrightTimeoutError("ChatGPT submit button did not become ready.")

    async def stream_response(
        self,
        previous_assistant_count: int,
        previous_assistant_text: str,
        timeout: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream the latest assistant response."""
        timeout = RESPONSE_TIMEOUT if timeout is None else timeout

        start = time.monotonic()
        previous_text = previous_assistant_text.strip()
        current_text = previous_text
        last_change = start

        response_started = False
        generation_seen = False

        while time.monotonic() - start < timeout:
            snapshot = await self._response_snapshot()

            latest_text = str(snapshot["text"])
            assistant_count = int(snapshot["count"])
            state = str(snapshot["state"])

            now = time.monotonic()

            if assistant_count > previous_assistant_count:
                response_started = True

            if latest_text != previous_text:
                response_started = True

            if state == "generating":
                response_started = True
                generation_seen = True

            if latest_text != current_text:
                delta = self._delta(
                    current_text,
                    latest_text,
                )

                current_text = latest_text
                last_change = now

                if delta:
                    yield delta

            if response_started and current_text:
                stable_for = now - last_change

                if generation_seen and state == "ready" and stable_for >= 0.25:
                    await asyncio.sleep(FINAL_CHECK_DELAY)

                    final = await self._response_snapshot()
                    final_text = str(final["text"])

                    if final_text != current_text:
                        delta = self._delta(
                            current_text,
                            final_text,
                        )

                        if delta:
                            yield delta

                        current_text = final_text

                    return

                if not generation_seen and stable_for >= STABLE_TIME:
                    await asyncio.sleep(FINAL_CHECK_DELAY)

                    final = await self._response_snapshot()
                    final_text = str(final["text"])

                    if final_text == current_text:
                        return

                    delta = self._delta(
                        current_text,
                        final_text,
                    )

                    if delta:
                        yield delta

                    current_text = final_text
                    last_change = time.monotonic()

            if state == "generating":
                delay = 0.05
            elif response_started:
                delay = 0.10
            else:
                delay = max(POLL_INTERVAL, 0.10)

            await asyncio.sleep(delay)

        if response_started and current_text:
            final = await self._response_snapshot()
            final_text = str(final["text"])

            if final_text != current_text:
                delta = self._delta(
                    current_text,
                    final_text,
                )

                if delta:
                    yield delta

            return

        raise TimeoutError("Timed out waiting for ChatGPT response.")

    @staticmethod
    def _delta(
        previous: str,
        current: str,
    ) -> str:
        """Return the new portion of a response."""
        if current.startswith(previous):
            return current[len(previous) :]

        return current

    async def ask(
        self,
        prompt: str,
        timeout: float | None = None,
    ) -> str:
        """Send a prompt and return the complete response."""
        previous_count = await self.assistant_count()
        previous_text = await self.latest_assistant_text()

        await self.submit_prompt(prompt)

        chunks: list[str] = []

        async for chunk in self.stream_response(
            previous_assistant_count=previous_count,
            previous_assistant_text=previous_text,
            timeout=timeout,
        ):
            chunks.append(chunk)

        response = "".join(chunks)
        self._last_response = response

        return response

    async def ask_stream(
        self,
        prompt: str,
        timeout: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Send a prompt and stream its response."""
        previous_count = await self.assistant_count()
        previous_text = await self.latest_assistant_text()

        await self.submit_prompt(prompt)

        chunks: list[str] = []

        async for chunk in self.stream_response(
            previous_assistant_count=previous_count,
            previous_assistant_text=previous_text,
            timeout=timeout,
        ):
            chunks.append(chunk)
            yield chunk

        self._last_response = "".join(chunks)

    @property
    def last_response(self) -> str:
        """Return the last completed response."""
        return self._last_response
