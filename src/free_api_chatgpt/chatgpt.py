import asyncio
import time
from collections.abc import AsyncGenerator

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from free_api_chatgpt.config import (
    CHAT_ID,
    HEADLESS,
    INTERNAL_CONTEXT,
)


class ChatGPT:
    """Browser-based ChatGPT client."""

    def __init__(
        self,
        page: Page,
        context=None,
        chat_id=None,
    ):
        self.page = page
        self.context = context or INTERNAL_CONTEXT
        self.chat_id = chat_id or CHAT_ID
        self.headless = HEADLESS
        self._last_response = ""

    async def composer(self) -> Locator:
        """Return the ChatGPT message composer."""
        composer = self.page.get_by_role("textbox").first

        await composer.wait_for(
            state="visible",
            timeout=30000,
        )

        return composer

    async def find_submit_button(self) -> Locator:
        """Find the exact ChatGPT submit button."""
        button = self.page.locator("#composer-submit-button")

        await button.wait_for(
            state="visible",
            timeout=30000,
        )

        return button

    async def submit_button_state(self) -> str:
        """Read the submit button state directly from the DOM."""
        return await self.page.evaluate(
            """
            () => {
                const button =
                    document.querySelector("#composer-submit-button");

                if (!button) {
                    return "missing";
                }

                const ariaDisabled =
                    button.getAttribute("aria-disabled");

                const ariaLabel =
                    (
                        button.getAttribute("aria-label") || ""
                    ).toLowerCase();

                if (
                    button.disabled ||
                    ariaDisabled === "true"
                ) {
                    return "disabled";
                }

                if (
                    ariaLabel.includes("stop") ||
                    ariaLabel.includes("cancel") ||
                    ariaLabel.includes("interrupt")
                ) {
                    return "busy";
                }

                return "ready";
            }
            """
        )

    async def generation_state(self) -> str:
        """Read the generation state directly from the DOM."""
        return await self.page.evaluate(
            """
            () => {
                const submit =
                    document.querySelector("#composer-submit-button");

                if (!submit) {
                    return "unknown";
                }

                const ariaDisabled =
                    submit.getAttribute("aria-disabled");

                const ariaLabel =
                    (
                        submit.getAttribute("aria-label") || ""
                    ).toLowerCase();

                if (
                    submit.disabled ||
                    ariaDisabled === "true"
                ) {
                    return "generating";
                }

                if (
                    ariaLabel.includes("stop") ||
                    ariaLabel.includes("cancel") ||
                    ariaLabel.includes("interrupt")
                ) {
                    return "generating";
                }

                return "ready";
            }
            """
        )

    async def assistant_messages(self) -> Locator:
        """Return assistant message elements."""
        return self.page.locator('[data-message-author-role="assistant"]')

    async def assistant_count(self) -> int:
        """Return the number of assistant messages."""
        return await (await self.assistant_messages()).count()

    async def get_latest_assistant_text(self) -> str:
        """Return the latest assistant response."""
        return await self.page.evaluate(
            """
            () => {
                const messages =
                    document.querySelectorAll(
                        '[data-message-author-role="assistant"]'
                    );

                if (!messages.length) {
                    return "";
                }

                const message =
                    messages[messages.length - 1];

                return (
                    message.innerText || ""
                ).trim();
            }
            """
        )

    async def accept_cookies(self) -> None:
        """Accept the cookie dialog when present."""
        selectors = [
            'button:has-text("Accept")',
            'button:has-text("Accept all")',
            'button:has-text("Allow all")',
            'button:has-text("Agree")',
        ]

        for selector in selectors:
            locator = self.page.locator(selector)
            count = await locator.count()

            for index in range(count):
                button = locator.nth(index)

                if await button.is_visible():
                    try:
                        await button.click(timeout=3000)
                    except PlaywrightTimeoutError:
                        pass

                    return

    async def initialize_page(self) -> None:
        """Open ChatGPT and wait for the composer."""
        if self.chat_id:
            url = f"https://chatgpt.com/c/{self.chat_id}"
        else:
            url = "https://chatgpt.com"

        await self.page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await asyncio.sleep(3)

        await self.accept_cookies()

        await self.composer()

    async def submit_prompt(
        self,
        prompt: str,
    ) -> None:
        """Fill and submit a prompt."""
        composer = await self.composer()

        await composer.fill(prompt)

        button = await self.find_submit_button()

        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            state = await self.submit_button_state()

            if state == "ready":
                await button.click(timeout=10000)
                return

            await asyncio.sleep(0.05)

        raise PlaywrightTimeoutError("ChatGPT submit button did not become ready.")

    async def wait_for_response(
        self,
        previous_assistant_count: int,
        previous_assistant_text: str,
        timeout: float = 120,
    ) -> str:
        """Wait until the assistant response stops changing."""
        start = time.monotonic()

        previous_text = (previous_assistant_text or "").strip()

        last_text = previous_text
        response_started = False
        last_change = None

        while time.monotonic() - start < timeout:
            current_text = await self.get_latest_assistant_text()

            if current_text and current_text != previous_text:
                response_started = True

            if current_text != last_text:
                last_text = current_text
                last_change = time.monotonic()

            if response_started and last_text:
                if last_change is None:
                    last_change = time.monotonic()

                if time.monotonic() - last_change >= 0.8:
                    await asyncio.sleep(0.15)

                    final_text = await self.get_latest_assistant_text()

                    if final_text == last_text:
                        return final_text

                    last_text = final_text
                    last_change = time.monotonic()

            await asyncio.sleep(0.05)

        if response_started and last_text:
            return last_text

        raise TimeoutError("Timed out waiting for ChatGPT response.")

    async def stream_response(
        self,
        previous_assistant_count: int,
        previous_assistant_text: str,
        timeout: float = 120,
    ) -> AsyncGenerator[str, None]:
        """Stream the assistant response until its text is stable."""
        start = time.monotonic()

        previous_text = (previous_assistant_text or "").strip()

        current_text = previous_text
        response_started = False
        last_change = None

        while time.monotonic() - start < timeout:
            latest_text = await self.get_latest_assistant_text()

            if latest_text and latest_text != previous_text:
                response_started = True

            if latest_text != current_text:
                if latest_text.startswith(current_text):
                    delta = latest_text[len(current_text) :]
                else:
                    delta = latest_text

                current_text = latest_text
                last_change = time.monotonic()

                if delta:
                    yield delta

            if response_started and current_text:
                if last_change is None:
                    last_change = time.monotonic()

                if time.monotonic() - last_change >= 0.8:
                    await asyncio.sleep(0.15)

                    final_text = await self.get_latest_assistant_text()

                    if final_text == current_text:
                        return

                    if final_text.startswith(current_text):
                        delta = final_text[len(current_text) :]
                    else:
                        delta = final_text

                    current_text = final_text
                    last_change = time.monotonic()

                    if delta:
                        yield delta

            await asyncio.sleep(0.05)

        if response_started and current_text:
            final_text = await self.get_latest_assistant_text()

            if final_text != current_text:
                if final_text.startswith(current_text):
                    delta = final_text[len(current_text) :]
                else:
                    delta = final_text

                if delta:
                    yield delta

            return

        raise TimeoutError("Timed out waiting for ChatGPT response.")

    async def initialize_context(self) -> None:
        """Send the configured context to ChatGPT."""
        if not self.context:
            return

        previous_count = await self.assistant_count()
        previous_text = await self.get_latest_assistant_text()

        await self.submit_prompt(self.context)

        await self.wait_for_response(
            previous_assistant_count=previous_count,
            previous_assistant_text=previous_text,
        )

    async def ask(
        self,
        prompt: str,
    ) -> str:
        """Send a prompt and return the complete response."""
        previous_count = await self.assistant_count()
        previous_text = await self.get_latest_assistant_text()

        await self.submit_prompt(prompt)

        response = await self.wait_for_response(
            previous_assistant_count=previous_count,
            previous_assistant_text=previous_text,
        )

        self._last_response = response

        return response

    async def ask_stream(
        self,
        prompt: str,
    ) -> AsyncGenerator[str, None]:
        """Send a prompt and stream the complete response."""
        previous_count = await self.assistant_count()
        previous_text = await self.get_latest_assistant_text()

        await self.submit_prompt(prompt)

        chunks = []

        async for chunk in self.stream_response(
            previous_assistant_count=previous_count,
            previous_assistant_text=previous_text,
        ):
            chunks.append(chunk)
            yield chunk

        self._last_response = "".join(chunks)
