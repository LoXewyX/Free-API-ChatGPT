import asyncio
from collections.abc import AsyncIterator

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .config import (
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
        return self.page.locator("button.wm-composer-submitButton")

    def assistant_messages(self):
        return self.page.locator('div[class*="assistantMessage"]')

    def assistant_message_copies(self):
        return self.page.locator(
            'ol[class*="messageList"] > li '
            'div[class*="assistantMessage"] '
            'div[class*="messageCopy"]'
        )

    async def initialize_page(self):
        print("OPENING CHATGPT")

        await self.page.goto(
            "https://chatgpt.com",
            wait_until="domcontentloaded",
        )

        await self.page.wait_for_timeout(3000)

        print("ChatGPT page loaded.")

        await self.accept_cookies()

    async def accept_cookies(self):
        try:
            button = self.page.locator("button.wm-button--primary:nth-child(4)")

            if await button.is_visible(timeout=3000):
                print("Cookie dialog detected.")

                await button.click()

                await self.page.wait_for_timeout(1000)

                print("Cookies accepted.")

        except PlaywrightTimeoutError:
            pass

    async def assistant_count(self) -> int:
        return await self.assistant_messages().count()

    async def get_latest_assistant_text(self) -> str:
        copies = self.assistant_message_copies()

        count = await copies.count()

        if count == 0:
            return ""

        latest = copies.last

        try:
            text = await latest.inner_text()
            return text.strip()

        except PlaywrightTimeoutError:
            return ""

    async def submit_button_state(self) -> str:
        """
        Best-effort detection of the ChatGPT send/stop button.

        This is useful for streaming, but normal response
        completion does NOT depend on this method.
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
    ):
        composer = self.composer()

        print("Waiting for composer...")

        await composer.wait_for(
            state="visible",
            timeout=10_000,
        )

        print("Composer ready.")

        await composer.fill(prompt)

        print("Prompt entered.")

        await asyncio.sleep(0.25)

        submit = self.submit_button()

        try:
            await submit.wait_for(
                state="visible",
                timeout=5_000,
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

                        print("Prompt submitted.")

                        return

                    except PlaywrightTimeoutError:
                        break

                await asyncio.sleep(0.1)

        print("Send button unavailable. Using Enter fallback.")

        await composer.press("Enter")

        deadline = asyncio.get_running_loop().time() + 5.0

        while asyncio.get_running_loop().time() < deadline:
            count = await self.assistant_count()

            if count > 0:
                print("Prompt submitted.")
                return

            await asyncio.sleep(0.1)

        print("Prompt sent. Waiting for assistant response.")

    async def wait_for_new_assistant_message(
        self,
        previous_assistant_count: int,
    ):
        print(
            "Waiting for new assistant message "
            f"(previous count: "
            f"{previous_assistant_count})..."
        )

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        while True:
            count = await self.assistant_count()

            if count > previous_assistant_count:
                print(f"New assistant message detected (count: {count}).")

                return

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for new assistant message.")

            await asyncio.sleep(0.15)

    async def wait_for_response_text(self) -> str:
        print("Waiting for response text...")

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        while True:
            text = await self.get_latest_assistant_text()

            if text:
                print("Response text detected.")
                return text

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for assistant response text.")

            await asyncio.sleep(0.15)

    async def wait_for_stable_response(self) -> str:
        """
        Determines completion from the assistant DOM.

        We do NOT depend on the Send button.

        Once the response text remains unchanged for
        RESPONSE_STABLE_SECONDS, generation is considered
        complete.
        """

        print("Waiting for assistant response to stabilize...")

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        previous_text = None
        stable_since = None

        while True:
            current_text = await self.get_latest_assistant_text()

            if current_text:
                if current_text == previous_text:
                    if stable_since is None:
                        stable_since = asyncio.get_running_loop().time()

                    stable_for = asyncio.get_running_loop().time() - stable_since

                    if stable_for >= RESPONSE_STABLE_SECONDS:
                        print("Assistant response stabilized.")

                        return current_text.strip()

                else:
                    previous_text = current_text
                    stable_since = None

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for stable assistant response.")

            await asyncio.sleep(0.15)

    async def wait_for_response(
        self,
        previous_assistant_count: int,
    ) -> str:
        """
        NORMAL /chat response.

        No streaming.

        No dependency on the Send button.

        Flow:

            new assistant message
                    ↓
            response text appears
                    ↓
            response stops changing
                    ↓
            return complete response
        """

        await self.wait_for_new_assistant_message(previous_assistant_count)

        await self.wait_for_response_text()

        return await self.wait_for_stable_response()

    async def stream_response(
        self,
        previous_assistant_count: int,
    ) -> AsyncIterator[str]:
        """
        STREAMING-ONLY response.

        This method is used only by ask_stream().

        It observes changes to the assistant DOM and yields
        only newly added text.
        """

        await self.wait_for_new_assistant_message(previous_assistant_count)

        print("Streaming assistant response...")

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        previous_text = ""
        last_change_time = asyncio.get_running_loop().time()

        while True:
            current_text = await self.get_latest_assistant_text()

            now = asyncio.get_running_loop().time()

            if current_text:
                if current_text.startswith(previous_text):
                    delta = current_text[len(previous_text) :]

                    if delta:
                        yield delta

                        previous_text = current_text
                        last_change_time = now

                elif current_text != previous_text:
                    yield current_text

                    previous_text = current_text
                    last_change_time = now

                state = await self.submit_button_state()

                stable_for = now - last_change_time

                if state == "ready":
                    await asyncio.sleep(0.05)

                    final_text = await self.get_latest_assistant_text()

                    if final_text and final_text != previous_text:
                        if final_text.startswith(previous_text):
                            yield final_text[len(previous_text) :]
                        else:
                            yield final_text

                    print("Assistant stream finished.")

                    return

                if stable_for >= RESPONSE_STABLE_SECONDS:
                    await asyncio.sleep(0.05)

                    final_text = await self.get_latest_assistant_text()

                    if final_text == previous_text:
                        print("Assistant stream finished (DOM stabilized).")

                        return

                    if final_text:
                        if final_text.startswith(previous_text):
                            yield final_text[len(previous_text) :]
                        else:
                            yield final_text

                        previous_text = final_text
                        last_change_time = asyncio.get_running_loop().time()

            if now >= deadline:
                raise TimeoutError("Timed out streaming assistant response.")

            await asyncio.sleep(0.10)

    async def initialize_context(
        self,
        context: str,
    ):
        """
        Context initialization is always NORMAL.

        It does not stream.
        """

        previous_assistant_count = await self.assistant_count()

        print(f"Assistant message count before context: {previous_assistant_count}")

        await self.submit_prompt(context)

        await self.wait_for_response(previous_assistant_count)

        self.context_initialized = True

        print("ChatGPT context initialized.")

    async def ask(
        self,
        prompt: str,
    ) -> str:
        """
        NORMAL /chat API.

        This NEVER calls stream_response().
        """

        if not self.context_initialized:
            raise RuntimeError("ChatGPT internal context is not initialized.")

        previous_assistant_count = await self.assistant_count()

        await self.submit_prompt(prompt)

        response = await self.wait_for_response(previous_assistant_count)

        return response.strip()

    async def ask_stream(
        self,
        prompt: str,
    ) -> AsyncIterator[str]:
        """
        STREAMING /chat/stream API.

        This is the ONLY method that calls stream_response().
        """

        if not self.context_initialized:
            raise RuntimeError("ChatGPT internal context is not initialized.")

        previous_assistant_count = await self.assistant_count()

        await self.submit_prompt(prompt)

        async for chunk in self.stream_response(previous_assistant_count):
            yield chunk
