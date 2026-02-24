"""Browser automation tool using Playwright sync API.

Provides browser control for web CTF challenges that require
JavaScript rendering, form interaction, cookie manipulation, or
request interception.

Always opens in headful (visible) mode so the user can watch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from config import BrowserVisionConfig, load_config
from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class BrowserTool(BaseTool):
    """Browser for web challenges requiring JS or complex interaction.

    Features:
    - Always headful: opens a visible browser window for the user.
    - download_image: download images from the page for steg analysis.
    """

    name = "browser"
    description = (
        "Control a visible browser. Use for challenges "
        "requiring JavaScript rendering, form submission, cookie "
        "manipulation, multi-step navigation, or visual inspection. "
        "The browser opens headful so you can see the page. "
        "For simple HTTP requests, prefer the 'network' tool instead."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Browser action to perform.",
            enum=[
                "navigate",
                "click",
                "type",
                "get_text",
                "get_html",
                "screenshot",
                "execute_js",
                "get_cookies",
                "set_cookie",
                "list_forms",
                "list_links",
                "send_request",
                "intercept",
                "back",
                "download_image",
                "browser_close",
            ],
        ),
        ToolParameter(
            name="url",
            type="string",
            description=(
                "URL to navigate to (for 'navigate', 'send_request'), "
                "or image URL (for 'download_image')."
            ),
            required=False,
        ),
        ToolParameter(
            name="selector",
            type="string",
            description=(
                "CSS selector for element actions "
                "(click, type, get_text, get_html, download_image)."
            ),
            required=False,
        ),
        ToolParameter(
            name="text",
            type="string",
            description="Text to type into an element (for 'type' action).",
            required=False,
        ),
        ToolParameter(
            name="script",
            type="string",
            description="JavaScript code to execute (for 'execute_js').",
            required=False,
        ),
        ToolParameter(
            name="cookie_name",
            type="string",
            description="Cookie name (for 'set_cookie').",
            required=False,
        ),
        ToolParameter(
            name="cookie_value",
            type="string",
            description="Cookie value (for 'set_cookie').",
            required=False,
        ),
        ToolParameter(
            name="method",
            type="string",
            description="HTTP method for 'send_request' (GET, POST, etc.).",
            required=False,
        ),
        ToolParameter(
            name="headers",
            type="string",
            description="JSON string of headers for 'send_request'.",
            required=False,
        ),
        ToolParameter(
            name="data",
            type="string",
            description=(
                "Request body for 'send_request', "
                "or URL pattern for 'intercept'."
            ),
            required=False,
        ),
    ]

    def __init__(self, vision_config: BrowserVisionConfig | None = None) -> None:
        """Initialise without starting a browser.

        Args:
            vision_config: Optional watch config override.
                           If None, loaded from AppConfig.
        """
        cfg = load_config()
        self.timeout = cfg.tool.browser_timeout_ms
        self._log = get_logger()
        self._playwright = None
        self._browser = None
        self._page = None

        # Watch config
        self._vcfg = vision_config or cfg.browser_vision

        # OCR config
        self._ocr_cfg = cfg.ocr

        # Screenshots directory (for manual screenshot/download_image saves)
        self._screenshots_dir = Path("sessions/screenshots")
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_count = 0

    def _ensure_browser(self) -> None:
        """Lazily start the browser on first use (always headful)."""
        if self._page is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Install it with:\n"
                "  pip install playwright && playwright install chromium"
            )

        self._playwright = sync_playwright().start()

        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        if self._vcfg.slow_mo_ms:
            launch_kwargs["slow_mo"] = self._vcfg.slow_mo_ms

        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        context = self._browser.new_context(
            ignore_https_errors=True,
            viewport={
                "width": self._vcfg.viewport_width,
                "height": self._vcfg.viewport_height,
            },
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        self._page = context.new_page()
        self._page.set_default_timeout(self.timeout)

        self._log.info("Browser started (Chromium headful)")

    def _close_browser(self) -> None:
        """Shut down the browser and Playwright."""
        if self._page is not None:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __del__(self) -> None:
        """Cleanup guard."""
        self._close_browser()

    def execute(self, **kwargs: Any) -> str:
        """Dispatch to the appropriate browser action.

        Args:
            **kwargs: Must contain 'action'. Other params per action.

        Returns:
            Action result as string.
        """
        action: str = kwargs["action"]

        if action == "browser_close":
            self._close_browser()
            return "Browser closed."

        self._ensure_browser()

        dispatch = {
            "navigate": self._navigate,
            "click": self._click,
            "type": self._type,
            "get_text": self._get_text,
            "get_html": self._get_html,
            "screenshot": self._screenshot,
            "execute_js": self._execute_js,
            "get_cookies": self._get_cookies,
            "set_cookie": self._set_cookie,
            "list_forms": self._list_forms,
            "list_links": self._list_links,
            "send_request": self._send_request,
            "intercept": self._intercept,
            "back": self._back,
            "download_image": self._download_image,
        }

        handler = dispatch.get(action)
        if handler is None:
            return f"[ERROR] Unknown browser action: {action}"

        return handler(**kwargs)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _navigate(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        if not url:
            return "[ERROR] 'url' is required for navigate."
        resp = self._page.goto(url, wait_until="domcontentloaded")
        status = resp.status if resp else "unknown"
        title = self._page.title()
        return f"Navigated to {url}\nStatus: {status}\nTitle: {title}"

    def _click(self, **kwargs: Any) -> str:
        selector = kwargs.get("selector", "")
        if not selector:
            return "[ERROR] 'selector' is required for click."
        self._page.click(selector)
        self._page.wait_for_load_state("domcontentloaded")
        return f"Clicked: {selector}\nCurrent URL: {self._page.url}"

    def _type(self, **kwargs: Any) -> str:
        selector = kwargs.get("selector", "")
        text = kwargs.get("text", "")
        if not selector:
            return "[ERROR] 'selector' is required for type."
        self._page.fill(selector, text)
        return f"Typed into {selector}: {text}"

    def _get_text(self, **kwargs: Any) -> str:
        selector = kwargs.get("selector", "")
        if selector:
            el = self._page.query_selector(selector)
            if el is None:
                return f"[ERROR] Element not found: {selector}"
            return el.inner_text()
        return self._page.inner_text("body")

    def _get_html(self, **kwargs: Any) -> str:
        selector = kwargs.get("selector", "")
        if selector:
            el = self._page.query_selector(selector)
            if el is None:
                return f"[ERROR] Element not found: {selector}"
            return el.inner_html()
        return self._page.content()

    def _screenshot(self, **kwargs: Any) -> str:
        """Manual screenshot — saves to disk for user reference."""
        self._screenshot_count += 1
        path = self._screenshots_dir / f"manual_{self._screenshot_count}.png"
        try:
            self._page.screenshot(path=str(path), full_page=False)
            result = f"Screenshot saved: {path}\nURL: {self._page.url}"
            if self._ocr_cfg.enabled:
                try:
                    from utils.ocr import analyze_image
                    ocr_text = analyze_image(
                        path.read_bytes(),
                        load_config().model.api_key,
                        self._ocr_cfg.model,
                        self._ocr_cfg.max_tokens,
                    )
                    if ocr_text:
                        result += f"\n\n[Vision Analysis]\n{ocr_text}"
                except Exception as exc:
                    self._log.warning(f"OCR failed on screenshot: {exc}")
            return result
        except Exception as exc:
            return f"[ERROR] Screenshot failed: {exc}"

    def _execute_js(self, **kwargs: Any) -> str:
        script = kwargs.get("script", "")
        if not script:
            return "[ERROR] 'script' is required for execute_js."
        result = self._page.evaluate(script)
        return json.dumps(result, default=str, ensure_ascii=False)

    def _get_cookies(self, **kwargs: Any) -> str:
        cookies = self._page.context.cookies()
        if not cookies:
            return "No cookies set."
        lines = []
        for c in cookies:
            lines.append(
                f"  {c['name']}={c['value']} "
                f"(domain={c.get('domain', '?')})"
            )
        return "Cookies:\n" + "\n".join(lines)

    def _set_cookie(self, **kwargs: Any) -> str:
        name = kwargs.get("cookie_name", "")
        value = kwargs.get("cookie_value", "")
        if not name:
            return "[ERROR] 'cookie_name' is required for set_cookie."
        url = self._page.url
        self._page.context.add_cookies([{
            "name": name,
            "value": value,
            "url": url,
        }])
        return f"Cookie set: {name}={value} for {url}"

    def _list_forms(self, **kwargs: Any) -> str:
        forms = self._page.evaluate("""() => {
            return Array.from(document.forms).map((f, i) => ({
                index: i,
                action: f.action,
                method: f.method,
                fields: Array.from(f.elements).map(e => ({
                    tag: e.tagName, name: e.name, type: e.type, id: e.id
                })).filter(e => e.name)
            }));
        }""")
        if not forms:
            return "No forms found on page."
        return json.dumps(forms, indent=2, ensure_ascii=False)

    def _list_links(self, **kwargs: Any) -> str:
        links = self._page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: a.innerText.trim().substring(0, 80),
                href: a.href
            }));
        }""")
        if not links:
            return "No links found on page."
        lines = [f"  [{l['text']}] -> {l['href']}" for l in links[:50]]
        result = "\n".join(lines)
        if len(links) > 50:
            result += f"\n  ... and {len(links) - 50} more links"
        return f"Links ({len(links)}):\n{result}"

    def _send_request(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        method = kwargs.get("method", "GET").upper()
        raw_headers = kwargs.get("headers", "{}")
        data = kwargs.get("data")

        if not url:
            return "[ERROR] 'url' is required for send_request."

        try:
            headers = json.loads(raw_headers) if raw_headers else {}
        except json.JSONDecodeError:
            headers = {}

        js = f"""async () => {{
            const opts = {{
                method: {json.dumps(method)},
                headers: {json.dumps(headers)},
                credentials: 'include',
            }};
            {f'opts.body = {json.dumps(data)};' if data else ''}
            const resp = await fetch({json.dumps(url)}, opts);
            const text = await resp.text();
            const respHeaders = Object.fromEntries(resp.headers.entries());
            return {{
                status: resp.status,
                statusText: resp.statusText,
                headers: respHeaders,
                body: text.substring(0, 5000)
            }};
        }}"""
        result = self._page.evaluate(js)
        resp_headers = "\n".join(
            f"  {k}: {v}" for k, v in result.get("headers", {}).items()
        )
        return (
            f"HTTP {result['status']} {result['statusText']}\n"
            f"Headers:\n{resp_headers}\n\n"
            f"Body:\n{result['body']}"
        )

    def _intercept(self, **kwargs: Any) -> str:
        pattern = kwargs.get("data", "")
        if not pattern:
            return "[ERROR] 'data' (URL pattern) is required for intercept."

        captured: list[dict] = []

        def _handler(route):
            req = route.request
            captured.append({
                "method": req.method,
                "url": req.url,
                "headers": dict(req.headers),
                "post_data": req.post_data,
            })
            route.continue_()

        self._page.route(pattern, _handler)
        return (
            f"Intercept set for pattern: {pattern}\n"
            "Matching requests will be captured. Navigate or interact "
            "to trigger them, then use execute_js to check results."
        )

    def _back(self, **kwargs: Any) -> str:
        self._page.go_back(wait_until="domcontentloaded")
        return f"Navigated back. Current URL: {self._page.url}"

    def _download_image(self, **kwargs: Any) -> str:
        """Download an image from the page and save to disk.

        Accepts either a CSS selector (for an img element) or a direct
        URL via the 'url' parameter.
        """
        selector = kwargs.get("selector", "")
        img_url = kwargs.get("url", "")

        # Resolve image URL
        if not img_url and selector:
            src = self._page.get_attribute(selector, "src")
            if not src:
                return f"[ERROR] No src found on element: {selector}"
            img_url = src if src.startswith("http") else urljoin(
                self._page.url, src,
            )
        elif not img_url:
            return "[ERROR] 'url' or 'selector' required for download_image."

        try:
            # Download via page context (handles cookies/auth)
            api_resp = self._page.context.request.get(img_url)
            img_bytes = api_resp.body()
        except Exception as exc:
            return f"[ERROR] Failed to download image: {exc}"

        # Determine extension
        ext = img_url.rsplit(".", 1)[-1].split("?")[0][:4]
        if ext not in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"):
            ext = "png"

        # Save to disk
        self._screenshot_count += 1
        path = self._screenshots_dir / f"image_{self._screenshot_count}.{ext}"
        path.write_bytes(img_bytes)

        result = f"Image downloaded: {img_url}\nSaved to: {path}\nSize: {len(img_bytes)} bytes"
        if self._ocr_cfg.enabled:
            try:
                from utils.ocr import analyze_image
                ocr_text = analyze_image(
                    img_bytes,
                    load_config().model.api_key,
                    self._ocr_cfg.model,
                    self._ocr_cfg.max_tokens,
                )
                if ocr_text:
                    result += f"\n\n[Vision Analysis]\n{ocr_text}"
            except Exception as exc:
                self._log.warning(f"OCR failed on downloaded image: {exc}")
        return result
