import time
from pathlib import Path
from typing import Literal

from playwright._impl._api_structures import SetCookieParam
from playwright.async_api import (
    BrowserContext,
    Error,
    Page,
    Playwright,
    Route,
    async_playwright,
)

from .config import (
    COOKIES_JSON,
    HEADLESS,
    PROFILE_DIR,
)


class BrowserManager:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def _route_handler(self, route: Route):
        """
        Block resources that are not required by the application.

        CSS and JavaScript are intentionally kept because the application
        requires normal browser functionality.
        """
        if route.request.resource_type in {
            "image",
            "font",
            "media",
        }:
            await route.abort()
        else:
            await route.continue_()

    async def import_cookies(
        self,
        context: BrowserContext,
    ):
        if COOKIES_JSON is None:
            print("No cookies.json found. Skipping cookie import.")
            return

        valid_cookies: list[SetCookieParam] = []

        for cookie in COOKIES_JSON:
            if not isinstance(cookie, dict):
                continue

            name = cookie.get("name")
            value = cookie.get("value")

            if name is None or value is None:
                continue

            domain = cookie.get("domain")
            url = cookie.get("url")

            if domain is None and url is None:
                continue

            expires: float | None = None
            raw_expires = cookie.get("expires")

            if raw_expires is not None:
                if isinstance(raw_expires, bool):
                    continue

                try:
                    expires = float(raw_expires)
                except (TypeError, ValueError):
                    continue

            if expires is not None and expires > 0 and expires <= time.time():
                continue

            same_site: Literal["Lax", "None", "Strict"] | None = None
            raw_same_site = cookie.get("sameSite")

            if raw_same_site is not None:
                normalized = str(raw_same_site).strip().lower()

                if normalized == "strict":
                    same_site = "Strict"
                elif normalized == "lax":
                    same_site = "Lax"
                elif normalized in (
                    "none",
                    "no_restriction",
                ):
                    same_site = "None"

            cleaned: SetCookieParam = {
                "name": str(name),
                "value": str(value),
            }

            if domain is not None:
                cleaned["domain"] = str(domain)

            if url is not None:
                cleaned["url"] = str(url)

            path = cookie.get("path")

            if path is not None:
                cleaned["path"] = str(path)

            if expires is not None:
                cleaned["expires"] = expires

            http_only = cookie.get("httpOnly")

            if isinstance(http_only, bool):
                cleaned["httpOnly"] = http_only

            secure = cookie.get("secure")

            if isinstance(secure, bool):
                cleaned["secure"] = secure

            if same_site is not None:
                cleaned["sameSite"] = same_site

            valid_cookies.append(cleaned)

        if not valid_cookies:
            print("No valid cookies found.")
            return

        try:
            await context.add_cookies(valid_cookies)

        except Error as exc:
            print(f"Failed to import cookies: {exc}")

    async def start(self) -> Page:
        profile = Path(PROFILE_DIR).resolve()

        profile.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.playwright = await async_playwright().start()

        context = await self.playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile),
            headless=HEADLESS,
            viewport={
                "width": 1400,
                "height": 900,
            },
            firefox_user_prefs={
                "permissions.default.microphone": 1,
                "permissions.default.persistent-storage": 1,
                "dom.ipc.processCount": 1,
                "browser.sessionstore.interval": 60000,
                "browser.sessionstore.resume_from_crash": False,
                "network.prefetch-next": False,
                "network.predictor.enabled": False,
                "network.http.speculative-parallel-limit": 0,
            },
        )

        self.context = context

        await context.route("**/*", self._route_handler)

        existing_cookies = await context.cookies()

        if not existing_cookies:
            await self.import_cookies(context)

        if context.pages:
            self.page = context.pages[0]
        else:
            self.page = await context.new_page()

        return self.page

    async def stop(self):
        try:
            if self.context:
                await self.context.unroute(
                    "**/*",
                    self._route_handler,
                )

                await self.context.close()

        finally:
            self.context = None
            self.page = None

        try:
            if self.playwright:
                await self.playwright.stop()

        finally:
            self.playwright = None
