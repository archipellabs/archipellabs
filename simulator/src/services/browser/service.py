from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import BrowserContext, async_playwright

from src.config import settings


@asynccontextmanager
async def browser_session(headless: bool = True) -> AsyncIterator[BrowserContext]:
    """Async Playwright context: one browser, one isolated context per call."""
    args = ["--no-sandbox"] if settings.browser_no_sandbox else []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=args)
        context = await browser.new_context(ignore_https_errors=True)
        try:
            yield context
        finally:
            await context.close()
            await browser.close()
