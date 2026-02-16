"""Browser automation tool using Playwright sync API.

Provides headless browser control for web CTF challenges that require
JavaScript rendering, form interaction, cookie manipulation, or
request interception.

Supports Vision Mode (auto-screenshot + model vision analysis) and
Watch Mode (visible browser window for debugging).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from config import BrowserVisionConfig, load_config
from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class VisionController:
    """Control when to use vision (screenshot) to save tokens.

    Screenshots cost ~1000 tokens each. Default behaviour is OFF —
    only screenshot when there's a concrete reason to believe the
    page contains visual-only content (very short text, explicit
    image challenge hints, or the agent explicitly asks for it).

    The agent can always call ``action="screenshot"`` manually;
    this controller only gates the *automatic* screenshots that
    happen after navigate/click.
    """

    def __init__(self, max_screenshots: int = 5) -> None:
        self.screenshots_sent = 0
        self.max_screenshots = max_screenshots

    def should_screenshot(
        self,
        page_text: str,
        action: str,
        page_html: str = "",
    ) -> bool:
        """Decide if this page state needs an automatic screenshot.

        Conservative by default — only returns True when there is a
        positive signal that visual analysis is needed.

        Args:
            page_text: ``innerText("body")`` — visible text only.
            action: The browser action that just executed.
            page_html: Raw HTML of the page (optional, for tag checks).
        """
        # Hard budget cap
        if self.screenshots_sent >= self.max_screenshots:
            return False

        # Already found flag in text → no point screenshotting
        if re.search(r'flag\{[^}]+\}', page_text, re.I):
            return False

        text_len = len(page_text.strip())

        # --- Positive signals (need vision) ---

        # Page has almost no visible text → content is probably
        # rendered in images / canvas / JS that innerText misses
        if text_len < 50:
            return True

        # HTML contains <canvas> — often used to render flags visually
        if page_html and "<canvas" in page_html.lower():
            return True

        # Visible text explicitly mentions visual clues
        lower_text = page_text.lower()
        if any(kw in lower_text for kw in [
            "captcha", "qr code", "scan this", "look at the image",
            "what do you see", "hidden in the image",
        ]):
            return True

        # --- Everything else: no auto-screenshot ---
        # The agent can still call action="screenshot" or
        # action="download_image" manually when it suspects
        # visual content.
        return False

    def record_screenshot(self) -> None:
        self.screenshots_sent += 1

    def reset(self) -> None:
        self.screenshots_sent = 0


class BrowserTool(BaseTool):
    """Headless browser for web challenges requiring JS or complex interaction.

    Features:
    - Vision Mode: auto-screenshot on navigate/click/submit, returned as
      base64 for model vision analysis.
    - Watch Mode: opens a visible browser window for debugging.
    - download_image: download images from the page for steg analysis.
    """

    name = "browser"
    description = (
        "Control a browser (with optional vision). Use for challenges "
        "requiring JavaScript rendering, form submission, cookie "
        "manipulation, multi-step navigation, or visual analysis. "
        "Vision mode auto-screenshots pages so the model can SEE them. "
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
            vision_config: Optional vision/watch config override.
                           If None, loaded from AppConfig.
        """
        cfg = load_config()
        self.timeout = cfg.tool.browser_timeout_ms
        self._log = get_logger()
        self._playwright = None
        self._browser = None
        self._page = None

        # Vision / watch config
        self._vcfg = vision_config or cfg.browser_vision
        self._vision_ctrl = VisionController(
            max_screenshots=self._vcfg.max_screenshots,
        )

        # Screenshots directory
        self._screenshots_dir = Path("sessions/screenshots")
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_count = 0

    def _ensure_browser(self) -> None:
        """Lazily start the browser on first use."""
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
            "headless": not self._vcfg.watch_mode,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        if self._vcfg.watch_mode:
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

        mode = "watch" if self._vcfg.watch_mode else "headless"
        vision = "vision ON" if self._vcfg.vision_enabled else "vision OFF"
        self._log.info(f"Browser started (Chromium {mode}, {vision})")

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
            Action result as string (may include __VISION_B64__ markers
            for the orchestrator to detect and convert to vision messages).
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
    # Vision helpers
    # ------------------------------------------------------------------

    def _take_screenshot(self, label: str) -> str | None:
        """Take a screenshot and return base64, or None if vision disabled."""
        self._screenshot_count += 1
        path = self._screenshots_dir / f"{label}_{self._screenshot_count}.png"
        try:
            self._page.screenshot(path=str(path), full_page=False)
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            self._vision_ctrl.record_screenshot()
            return b64
        except Exception as exc:
            self._log.debug(f"Screenshot failed: {exc}")
            return None

    def _maybe_screenshot(self, action: str, text_output: str) -> str:
        """Conditionally append a vision screenshot to text output.

        Uses the ``__VISION_B64__::<base64data>`` marker so the
        orchestrator can detect it and convert to a multimodal message.

        Auto-screenshot is conservative — only fires when there's a
        concrete signal that visual analysis is needed (very short
        text, ``<canvas>`` tag, explicit visual-challenge keywords).
        The agent can always request a manual ``screenshot`` action.
        """
        if not self._vcfg.vision_enabled:
            return text_output

        # Gather page signals for the heuristic
        try:
            page_text = self._page.inner_text("body")
        except Exception:
            page_text = ""

        try:
            page_html = self._page.content()
            # Only keep first 5k chars for the tag check — no need to
            # send the whole DOM through the heuristic.
            page_html = page_html[:5000]
        except Exception:
            page_html = ""

        if not self._vision_ctrl.should_screenshot(
            page_text, action, page_html=page_html,
        ):
            return text_output

        b64 = self._take_screenshot(action)
        if b64:
            text_output += f"\n__VISION_B64__::{b64}"
        return text_output

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
        output = f"Navigated to {url}\nStatus: {status}\nTitle: {title}"
        return self._maybe_screenshot("navigate", output)

    def _click(self, **kwargs: Any) -> str:
        selector = kwargs.get("selector", "")
        if not selector:
            return "[ERROR] 'selector' is required for click."
        self._page.click(selector)
        self._page.wait_for_load_state("domcontentloaded")
        output = f"Clicked: {selector}\nCurrent URL: {self._page.url}"
        return self._maybe_screenshot("click", output)

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
        """Manual screenshot — always captures regardless of VisionController."""
        b64 = self._take_screenshot("manual")
        if b64:
            return (
                f"Screenshot captured. URL: {self._page.url}\n"
                f"__VISION_B64__::{b64}"
            )
        # Fallback: return raw bytes info
        raw = self._page.screenshot(full_page=True)
        b64_fallback = base64.b64encode(raw).decode()
        return (
            f"Screenshot captured ({len(raw)} bytes, base64):\n"
            f"{b64_fallback[:200]}..."
        )

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
        """Download an image from the page for analysis.

        Accepts either a CSS selector (for an img element) or a direct
        URL via the 'url' parameter. The image is saved to disk and
        returned as base64 for vision analysis.
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

        img_b64 = base64.b64encode(img_bytes).decode()

        return (
            f"Image downloaded: {img_url}\n"
            f"Saved to: {path}\n"
            f"Size: {len(img_bytes)} bytes\n"
            f"__VISION_B64__::{img_b64}"
        )
