import asyncio

from playwright.async_api import (
    Page,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

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

    async def submit_prompt(self, prompt: str):
        composer = self.composer()

        print("Waiting for composer...")

        await composer.wait_for(
            state="visible",
        )

        print("Composer ready.")

        await composer.fill(prompt)

        print("Prompt entered.")

        submit = self.submit_button()

        await submit.wait_for(
            state="visible",
        )

        print("Submit button found.")

        await submit.click()

        print("Prompt submitted.")

    async def submit_button_state(self) -> str:
        button = self.submit_button()

        try:
            if await button.count() == 0:
                return "generating"

            if not await button.is_visible():
                return "generating"

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

            return "ready"

        except PlaywrightTimeoutError:
            return "unknown"

    async def wait_for_generation_to_finish(self):
        print("Waiting for generation to finish...")

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        saw_generating = False

        while True:
            state = await self.submit_button_state()

            if state == "generating":
                saw_generating = True

            elif state == "ready":
                if saw_generating:
                    print("Generation finished.")
                else:
                    print("Submit button ready.")

                return

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for generation to finish.")

            await asyncio.sleep(0.25)

    async def wait_for_new_assistant_message(
        self,
        previous_assistant_count: int,
    ):
        print(
            "Waiting for new assistant message "
            f"(previous count: {previous_assistant_count})..."
        )

        deadline = asyncio.get_running_loop().time() + RESPONSE_TIMEOUT

        while True:
            count = await self.assistant_count()

            if count > previous_assistant_count:
                print(f"New assistant message detected (count: {count}).")
                return

            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for new assistant message.")

            await asyncio.sleep(0.25)

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

            await asyncio.sleep(0.25)

    async def wait_for_stable_response(self) -> str:
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

            await asyncio.sleep(0.25)

    async def wait_for_response(
        self,
        previous_assistant_count: int,
    ) -> str:
        await self.wait_for_new_assistant_message(previous_assistant_count)

        await self.wait_for_generation_to_finish()

        await self.wait_for_response_text()

        return await self.wait_for_stable_response()

    async def initialize_context(
        self,
        context: str,
    ):
        previous_assistant_count = await self.assistant_count()

        print(f"Assistant message count before context: {previous_assistant_count}")

        await self.submit_prompt(context)

        await self.wait_for_response(previous_assistant_count)

        self.context_initialized = True

    async def ask(
        self,
        prompt: str,
    ) -> str:
        if not self.context_initialized:
            raise RuntimeError("ChatGPT internal context is not initialized.")

        previous_assistant_count = await self.assistant_count()

        await self.submit_prompt(prompt)

        response = await self.wait_for_response(previous_assistant_count)

        return response.strip()
