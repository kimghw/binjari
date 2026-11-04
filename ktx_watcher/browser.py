"""Shared browser API: acquire execution contexts without Runtime.enable."""

import os

from rebrowser_playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError,
    sync_playwright as _sync_playwright,
)


def sync_playwright():
    # Set this at driver startup, after dotenv loading. Never fall back to
    # upstream Playwright or enableDisable, which would enable Runtime events.
    os.environ["REBROWSER_PATCHES_RUNTIME_FIX_MODE"] = "addBinding"
    return _sync_playwright()


__all__ = [
    "Browser", "BrowserContext", "Page", "Playwright", "TimeoutError",
    "sync_playwright",
]
