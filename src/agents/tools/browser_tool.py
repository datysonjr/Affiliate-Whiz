"""Browser automation tool for headless browser interactions.

Provides methods for navigating to pages, extracting content,
taking screenshots, and waiting for dynamic elements. Built on
top of Playwright for reliable cross-browser headless automation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class BrowserTool:
    """Headless browser automation tool.

    Wraps a headless browser (Playwright) to navigate pages, capture
    screenshots, extract rendered content, and wait for dynamically
    loaded elements.  Designed for use inside agent pipelines where
    JavaScript-rendered pages must be inspected.

    Attributes:
        config: Dictionary holding browser configuration such as
            ``headless`` (bool), ``timeout`` (int, ms), ``viewport``
            (dict with ``width``/``height``), ``user_agent`` (str),
            and ``proxy`` (optional dict).
        _browser: Internal browser instance (lazily initialised).
        _context: Internal browser context for isolation.
        _page: Active page object for the current session.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialise BrowserTool with the given configuration.

        Args:
            config: Configuration dictionary.  Recognised keys:

                * ``headless`` (bool) -- run in headless mode.  Default ``True``.
                * ``timeout`` (int) -- default navigation timeout in
                  milliseconds.  Default ``30000``.
                * ``viewport`` (dict) -- keys ``width`` and ``height``.
                  Default ``{"width": 1280, "height": 720}``.
                * ``user_agent`` (str) -- custom User-Agent string.
                * ``proxy`` (dict) -- optional proxy settings with
                  ``server``, ``username``, ``password``.
        """
        self.config = config
        self._headless: bool = config.get("headless", True)
        self._timeout: int = config.get("timeout", 30_000)
        self._viewport: dict[str, int] = config.get(
            "viewport", {"width": 1280, "height": 720}
        )
        self._user_agent: Optional[str] = config.get("user_agent")
        self._proxy: Optional[dict[str, str]] = config.get("proxy")

        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

        logger.info(
            "BrowserTool initialised (headless=%s, timeout=%d ms)",
            self._headless,
            self._timeout,
        )

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        """Lazily launch the browser and create a context/page.

        This is called automatically by the public methods so that
        callers do not need to manage the browser lifecycle manually.

        Raises:
            RuntimeError: If Playwright is not installed or the
                browser binary cannot be found.
        """
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright  # type: ignore[import-untyped]

            pw = await async_playwright().start()

            launch_kwargs: dict[str, Any] = {"headless": self._headless}
            if self._proxy:
                launch_kwargs["proxy"] = self._proxy

            self._browser = await pw.chromium.launch(**launch_kwargs)

            context_kwargs: dict[str, Any] = {"viewport": self._viewport}
            if self._user_agent:
                context_kwargs["user_agent"] = self._user_agent

            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self._timeout)
            logger.debug("Browser launched successfully.")
        except Exception as exc:
            logger.error("Failed to launch browser: %s", exc)
            raise RuntimeError(
                "Could not start headless browser. "
                "Ensure playwright is installed and browsers are downloaded."
            ) from exc

    async def close(self) -> None:
        """Shut down the browser and release resources."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None
            logger.info("Browser closed.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> None:
        """Navigate the browser to the given URL.

        Waits until the page reaches the ``domcontentloaded`` state
        before returning.

        Args:
            url: Fully-qualified URL to navigate to
                (e.g. ``https://example.com``).

        Raises:
            RuntimeError: If the browser cannot be started.
            TimeoutError: If navigation exceeds the configured timeout.
        """
        await self._ensure_browser()
        logger.info("Navigating to %s", url)

        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            logger.debug("Navigation to %s completed.", url)
        except Exception as exc:
            logger.error("Navigation to %s failed: %s", url, exc)
            raise

    async def get_page_content(self, url: str) -> str:
        """Navigate to *url* and return the fully-rendered HTML content.

        This first navigates to the page (waiting for
        ``domcontentloaded``) and then returns the outer HTML of the
        document element.

        Args:
            url: The URL whose content should be fetched.

        Returns:
            The full HTML source of the rendered page as a string.

        Raises:
            RuntimeError: If the browser cannot be started.
            TimeoutError: If the page does not load within the timeout.
        """
        await self.navigate(url)
        logger.info("Extracting page content for %s", url)

        content: str = await self._page.content()
        logger.debug(
            "Extracted %d characters of content from %s.",
            len(content),
            url,
        )
        return content

    async def screenshot(self, url: str, path: str) -> None:
        """Navigate to *url* and save a screenshot to *path*.

        The output format is inferred from the file extension of *path*
        (PNG or JPEG).  The screenshot captures the full page including
        content below the fold.

        Args:
            url: The URL to screenshot.
            path: Destination file path for the screenshot image
                (e.g. ``/tmp/shot.png``).

        Raises:
            RuntimeError: If the browser cannot be started.
            TimeoutError: If the page does not load within the timeout.
            OSError: If the screenshot file cannot be written.
        """
        await self.navigate(url)
        logger.info("Taking screenshot of %s -> %s", url, path)

        try:
            await self._page.screenshot(path=path, full_page=True)
            logger.debug("Screenshot saved to %s.", path)
        except Exception as exc:
            logger.error("Screenshot failed: %s", exc)
            raise

    async def wait_for_element(
        self,
        selector: str,
        timeout: Optional[int] = None,
    ) -> bool:
        """Wait for a DOM element matching *selector* to appear.

        Useful after a navigation or an action that triggers dynamic
        content loading (e.g. infinite scroll, AJAX fetch).

        Args:
            selector: CSS selector string for the target element
                (e.g. ``"div.product-card"``).
            timeout: Maximum time to wait in milliseconds.  Falls back
                to the instance-level timeout if ``None``.

        Returns:
            ``True`` if the element appeared within the timeout window,
            ``False`` otherwise.

        Raises:
            RuntimeError: If the browser has not been started and no
                page is open.
        """
        await self._ensure_browser()
        effective_timeout = timeout if timeout is not None else self._timeout
        logger.info(
            "Waiting for selector '%s' (timeout=%d ms)",
            selector,
            effective_timeout,
        )

        try:
            await self._page.wait_for_selector(
                selector, timeout=effective_timeout
            )
            logger.debug("Selector '%s' found.", selector)
            return True
        except Exception:
            logger.warning(
                "Selector '%s' not found within %d ms.",
                selector,
                effective_timeout,
            )
            return False
