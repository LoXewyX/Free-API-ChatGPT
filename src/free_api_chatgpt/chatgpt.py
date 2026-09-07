import asyncio
from collections.abc import AsyncIterator

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .config import (
    CHAT_ID,
    RESPONSE_STABLE_SECONDS,
    RESPONSE_TIMEOUT,
)


class ChatGPT:
    def __init__(self, page: Page):
        self.page = page
        self.context_initialized = False

    def composer(self):
        return self.page.get_by_role("textbox").first

    def submit_button(self):
        """
        Supports both older and newer ChatGPT submit-button classes.
        """
        return self.page.locator(
            'button.wm-composer-submitButton, button[class*="composer-submit-button"]'
        ).first

    def assistant_messages(self):
        return self.page.locator(
            '[data-message-author-role="assistant"], div[class*="assistantMessage"]'
        )

    async def initialize_page(self):
        await self.page.goto(
            f"https://chatgpt.com/c/{CHAT_ID}" if CHAT_ID else "https://chatgpt.com",
            wait_until="domcontentloaded",
        )

        await self.page.wait_for_timeout(3000)

        await self.accept_cookies()

    async def accept_cookies(self):
        try:
            button = self.page.locator("button.wm-button--primary:nth-child(4)")

            if await button.is_visible(timeout=3000):
                await button.click()

                await self.page.wait_for_timeout(1000)

        except PlaywrightTimeoutError:
            pass

    async def assistant_count(self) -> int:
        return await self.assistant_messages().count()

    async def get_latest_assistant_text(self) -> str:
        messages = self.assistant_messages()

        count = await messages.count()

        if count == 0:
            return ""

        latest = messages.nth(count - 1)

        try:
            text = await latest.inner_text()
            return text.strip()

        except PlaywrightTimeoutError:
            return ""

    async def submit_button_state(self) -> str:
        """
        Best-effort detection of the ChatGPT send/stop button.

        Returns:

            generating
            ready
            disabled
            unknown
        """

        button = self.submit_button()

        try:
            if await button.count() == 0:
                return "unknown"

            if not await button.is_visible():
                return "unknown"

            aria_disabled = await button.get_attribute("aria-disabled")

            disabled = await button.is_disabled()

            aria = (await button.get_attribute("aria-label") or "").lower()

            title = (await button.get_attribute("title") or "").lower()

            text = (await button.inner_text() or "").lower()

            value = f"{aria} {title} {text}"

            if any(
                word in value
                for word in (
                    "stop",
                    "cancel",
                    "interrupt",
                    "generating",
                )
            ):
                return "generating"

            if disabled:
                return "disabled"

            if aria_disabled == "true":
                return "disabled"

            return "ready"

        except PlaywrightTimeoutError:
            return "unknown"

    async def submit_prompt(
        self,
        prompt: str,
        previous_assistant_count: int,
    ):
        composer = self.composer()

        try:
            await composer.wait_for(
                state="visible",
                timeout=10_000,
            )
        except PlaywrightTimeoutError as exc:
            raise TimeoutError("Timed out waiting for ChatGPT composer.") from exc

        await composer.fill(prompt)

        await asyncio.sleep(0.1)

        submit = self.submit_button()

        try:
            await submit.wait_for(
                state="visible",
                timeout=3_000,
            )
        except PlaywrightTimeoutError:
            submit = None

        if submit is not None:
            deadline = asyncio.get_running_loop().time() + 5.0

            while asyncio.get_running_loop().time() < deadline:
                state = await self.submit_button_state()

                if state == "ready":
                    try:
                        await submit.click(timeout=2_000)

                        await self.wait_for_new_assistant_message(
                            previous_assistant_count
                        )

                        return

                    except PlaywrightTimeoutError:
                        pass

                await asyncio.sleep(0.05)

        raise TimeoutError(
            "ChatGPT Send button was unavailable or did not submit the prompt."
        )

    async def wait_for_new_assistant_message(
        self,
        previous_assistant_count: int,
    ):
        """
        Wait until ChatGPT creates a new assistant message.

        Polls approximately every 30 ms.
        """

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        while True:
            count = await self.assistant_count()

            if count > previous_assistant_count:
                return

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for new assistant message.")

            await asyncio.sleep(0.03)

    async def wait_for_response_text(self) -> str:
        """
        Wait until the latest assistant message
        contains text.

        Polls approximately every 30 ms.
        """

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        while True:
            text = await self.get_latest_assistant_text()

            if text:
                return text

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for assistant response text.")

            await asyncio.sleep(0.03)

    async def wait_for_stable_response(self) -> str:
        """
        Fallback DOM stabilization detector.

        Used when button state cannot reliably
        determine completion.
        """

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        previous_text = None
        stable_since = None

        while True:
            current_text = await self.get_latest_assistant_text()

            now = asyncio.get_running_loop().time()

            if current_text:
                if current_text == previous_text:
                    if stable_since is None:
                        stable_since = now

                    if now - stable_since >= RESPONSE_STABLE_SECONDS:
                        return current_text.strip()

                else:
                    previous_text = current_text
                    stable_since = None

            if now >= deadline:
                raise TimeoutError("Timed out waiting for stable assistant response.")

            await asyncio.sleep(0.03)

    async def wait_for_response(
        self,
        previous_assistant_count: int,
    ) -> str:
        """
        NORMAL /chat response.

        Fast completion path:

            new assistant message
                    ↓
            text appears
                    ↓
            button becomes ready
                    ↓
            final DOM read
                    ↓
            return immediately

        DOM stabilization is used as a fallback when
        the button is unknown or disabled.

        Hard timeout prevents infinite waiting.
        """

        await self.wait_for_new_assistant_message(previous_assistant_count)

        await self.wait_for_response_text()

        loop = asyncio.get_running_loop()

        deadline = loop.time() + RESPONSE_TIMEOUT

        last_text = await self.get_latest_assistant_text()

        last_change_time = loop.time()

        button_check_interval = 0.10

        last_button_check = 0.0

        button_state = "unknown"

        while True:
            now = loop.time()

            if now >= deadline:
                raise TimeoutError("Timed out waiting for assistant response.")

            current_text = await self.get_latest_assistant_text()

            if current_text != last_text:
                last_text = current_text
                last_change_time = now

            if now - last_button_check >= button_check_interval:
                last_button_check = now

                button_state = await self.submit_button_state()

                if button_state == "ready":
                    final_text = await self.get_latest_assistant_text()

                    if final_text:
                        return final_text.strip()

            if (
                button_state
                in (
                    "unknown",
                    "disabled",
                )
                and last_text
                and now - last_change_time >= RESPONSE_STABLE_SECONDS
            ):
                final_text = await self.get_latest_assistant_text()

                if final_text == last_text:
                    return final_text.strip()

            await asyncio.sleep(0.03)

    async def stream_response(
        self,
        previous_assistant_count: int,
    ) -> AsyncIterator[str]:
        """
        FAST streaming response.

        Assistant DOM is checked approximately
        every 30 ms.

        The submit button is checked approximately
        every 100 ms to avoid excessive Playwright
        round-trips.

        New text is yielded immediately.

        Completion uses:

            1. Send/ready button
            2. Final DOM read
            3. DOM stabilization fallback

        Hard timeout prevents infinite waiting.
        """

        await self.wait_for_new_assistant_message(previous_assistant_count)

        loop = asyncio.get_running_loop()

        deadline = loop.time() + RESPONSE_TIMEOUT

        previous_text = ""

        last_change_time = loop.time()

        last_button_check = 0.0

        button_state = "unknown"

        while True:
            now = loop.time()

            if now >= deadline:
                raise TimeoutError("Timed out streaming assistant response.")

            current_text = await self.get_latest_assistant_text()

            if current_text != previous_text:
                if current_text.startswith(previous_text):
                    delta = current_text[len(previous_text) :]
                else:
                    delta = current_text

                if delta:
                    yield delta

                previous_text = current_text

                last_change_time = now

            if now - last_button_check >= 0.10:
                last_button_check = now

                button_state = await self.submit_button_state()

                if button_state == "ready":
                    final_text = await self.get_latest_assistant_text()

                    if final_text != previous_text:
                        if final_text.startswith(previous_text):
                            delta = final_text[len(previous_text) :]
                        else:
                            delta = final_text

                        if delta:
                            yield delta

                    return

            if (
                button_state
                in (
                    "unknown",
                    "disabled",
                )
                and previous_text
                and (now - last_change_time >= RESPONSE_STABLE_SECONDS)
            ):
                final_text = await self.get_latest_assistant_text()

                if final_text == previous_text:
                    return

                if final_text:
                    if final_text.startswith(previous_text):
                        delta = final_text[len(previous_text) :]
                    else:
                        delta = final_text

                    if delta:
                        yield delta

                    previous_text = final_text

                    last_change_time = now

            await asyncio.sleep(0.03)

    async def initialize_context(
        self,
        context: str,
    ):
        """
        Context initialization is NORMAL.

        It does not stream.
        """

        previous_assistant_count = await self.assistant_count()

        await self.submit_prompt(
            context,
            previous_assistant_count,
        )

        await self.wait_for_response(previous_assistant_count)

        self.context_initialized = True

    async def ask(
        self,
        prompt: str,
    ) -> str:
        """
        NORMAL /chat API.

        Returns only after ChatGPT has finished.
        """

        if not self.context_initialized:
            raise RuntimeError("ChatGPT internal context is not initialized.")

        previous_assistant_count = await self.assistant_count()

        await self.submit_prompt(
            prompt,
            previous_assistant_count,
        )

        response = await self.wait_for_response(previous_assistant_count)

        return response.strip()

    async def ask_stream(
        self,
        prompt: str,
    ) -> AsyncIterator[str]:
        """
        STREAMING /chat/stream API.

        This is the only method that calls
        stream_response().
        """

        if not self.context_initialized:
            raise RuntimeError("ChatGPT internal context is not initialized.")

        previous_assistant_count = await self.assistant_count()

        await self.submit_prompt(
            prompt,
            previous_assistant_count,
        )

        async for chunk in self.stream_response(previous_assistant_count):
            yield chunk
