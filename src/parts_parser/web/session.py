import time
from types import TracebackType

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


class WebError(Exception):
    """Plain-language, user-facing."""


class BrowserSession:
    def __init__(self, min_request_interval: float = 0.5) -> None:
        self._min_interval = min_request_interval
        self._last_request: float = 0.0
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        self._page = self._context.new_page()
        return self

    def establish(self, base_url: str) -> None:
        assert self._page is not None, "Call __enter__ first"
        self._page.goto(base_url, wait_until="domcontentloaded", timeout=45_000)
        self._page.wait_for_timeout(5_000)
        title = self._page.title()
        body = self._page.inner_text("body")
        if (
            "attention required" in title.lower()
            or "just a moment" in title.lower()
            or "you have been blocked" in body.lower()
        ):
            raise WebError(
                "The website is blocking automated access. Try again in a few minutes."
            )

    def get_json(self, url: str) -> dict:
        assert self._context is not None, "Call __enter__ first"
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()
        resp = self._context.request.get(url)
        if resp.status != 200:
            raise WebError(f"The website returned an error (HTTP {resp.status}).")
        try:
            return resp.json()
        except Exception:
            raise WebError("The website sent an unexpected response.")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
