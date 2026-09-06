from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from .config import (
    HEADLESS,
    PROFILE_DIR,
)


class BrowserManager:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> Page:
        print("STARTING FIREFOX")

        profile = Path(PROFILE_DIR).resolve()

        profile.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.playwright = await async_playwright().start()

        print("Playwright started.")

        self.context = await self.playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile),
            headless=HEADLESS,
            viewport={
                "width": 1400,
                "height": 900,
            },
        )

        print("Firefox launched.")

        if self.context.pages:
            self.page = self.context.pages[0]

            print("Using existing Firefox page.")
        else:
            self.page = await self.context.new_page()

            print("Created new Firefox page.")

        print("FIREFOX READY")

        return self.page

    async def stop(self):
        print("STOPPING FIREFOX")

        try:
            if self.context:
                await self.context.close()
        finally:
            self.context = None
            self.page = None

        try:
            if self.playwright:
                await self.playwright.stop()
        finally:
            self.playwright = None
