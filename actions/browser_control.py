import asyncio
import threading
import concurrent.futures
import platform
import shutil
import subprocess
import re
from urllib.parse import quote_plus
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from core.lightpanda_bridge import collect_lightpanda_status


def _normalize_youtube_kind(query: str = "", requested_kind: str = "auto") -> str:
    requested = str(requested_kind or "auto").strip().lower()
    if requested in {"video", "videos", "normal", "full"}:
        return "video"
    if requested in {"short", "shorts"}:
        return "shorts"

    q = str(query or "").lower()
    if any(token in q for token in (" short ", " shorts", "shorts ", "#shorts", "youtube short")):
        return "shorts"
    return "video"


def _youtube_search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(str(query or '').strip())}"


def _looks_like_youtube_watch_url(url: str) -> bool:
    return "youtube.com/watch" in url or "youtu.be/" in url


def _looks_like_youtube_shorts_url(url: str) -> bool:
    return "/shorts/" in url


def _normalize_youtube_href(href: str) -> str:
    raw = str(href or "").strip()
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("/"):
        return "https://www.youtube.com" + raw
    return raw

def _get_default_browser_id() -> str:
    """Returns raw default browser identifier string for current OS."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key     = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
            )
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            winreg.CloseKey(key)
            return prog_id

        elif system == "Darwin":
            result = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

        elif system == "Linux":
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

def _get_default_browser_id() -> str:
    """Returns raw default browser identifier string for current OS."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key     = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
            )
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            winreg.CloseKey(key)
            return prog_id

        elif system == "Darwin":
            result = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

        elif system == "Linux":
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

    except Exception:
        pass

    return ""

_BROWSER_BINARIES = {
    "Windows": {
        "comet":   ["comet.exe"],
        "arc":     ["arc.exe"],
        "opera":   ["opera.exe", "launcher.exe"],
        "brave":   ["brave.exe"],
        "vivaldi": ["vivaldi.exe"],
        "chrome":  ["chrome.exe"],
        "edge":    ["msedge.exe"],
        "firefox": ["firefox.exe"],
    },
    "Darwin": {
        "comet":   ["comet"],
        "arc":     ["arc"],
        "opera":   ["opera"],
        "brave":   ["brave browser", "brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["google chrome", "google-chrome"],
        "edge":    ["microsoft edge"],
        "firefox": ["firefox"],
    },
    "Linux": {
        "comet":   ["comet"],
        "arc":     ["arc"],
        "opera":   ["opera", "opera-stable"],
        "brave":   ["brave-browser", "brave"],
        "vivaldi": ["vivaldi-stable", "vivaldi"],
        "chrome":  ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
        "edge":    ["microsoft-edge", "microsoft-edge-stable"],
        "firefox": ["firefox"],
    },
}

def _scan_windows_browser_paths(binary_names: list[str]) -> str | None:
    """Aggressively scan common Windows installation paths for browser executable."""
    if platform.system() != "Windows":
        return None
        
    common_dirs = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "C:\\Users\\Default\\AppData\\Local")),
        Path(os.environ.get("APPDATA", "C:\\Users\\Default\\AppData\\Roaming")),
    ]
    
    # Common subfolder patterns for browsers
    subfolders = [
        "Comet\\Application",
        "Google\\Chrome\\Application",
        "Microsoft\\Edge\\Application",
        "BraveSoftware\\Brave-Browser\\Application",
        "Vivaldi\\Application",
        "Opera Software\\Opera Stable",
        "Mozilla Firefox",
        "The Browser Company\\Arc",
    ]
    
    for base_dir in common_dirs:
        if not base_dir.exists(): continue
        for sub in subfolders:
            folder = base_dir / sub
            if not folder.exists(): continue
            for name in binary_names:
                exe_path = folder / name
                if exe_path.exists() and exe_path.is_file():
                    return str(exe_path)
    return None

import os

def _get_opera_executable() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
        candidate_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\launcher.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
        ]
        for key_path in candidate_keys:
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    key  = winreg.OpenKey(hive, key_path)
                    val  = winreg.QueryValue(key, None)
                    winreg.CloseKey(key)
                    # Strip quotes and args
                    exe  = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] Found Opera via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _find_browser_executable(prog_id: str) -> tuple:
    system  = platform.system()
    os_bins = _BROWSER_BINARIES.get(system, {})

    if any(x in prog_id for x in ["firefox", "mozilla"]):
        return "firefox", None, None

    if "safari" in prog_id:
        return "webkit", None, None

    if "edge" in prog_id:
        exe = _scan_windows_browser_paths(os_bins.get("edge", []))
        return "chromium", exe, "msedge" if not exe else None

    if "opera" in prog_id:
        exe = _get_opera_executable()
        if not exe: exe = _scan_windows_browser_paths(os_bins.get("opera", []))
        if exe: return "chromium", exe, None

    browser_patterns = {
        "comet":   ["comet"],
        "arc":     ["arc"],
        "brave":   ["brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["chrome"],
    }
    
    for browser_name, patterns in browser_patterns.items():
        if not any(p in prog_id for p in patterns):
            continue
            
        binaries = os_bins.get(browser_name, [])
        for binary in binaries:
            path = shutil.which(binary)
            if path:
                print(f"[Browser] Found {browser_name} in PATH: {path}")
                return "chromium", path, None
                
        exe = _scan_windows_browser_paths(binaries)
        if exe:
            print(f"[Browser] Found {browser_name} in system paths: {exe}")
            return "chromium", exe, None

    if "chrome" in prog_id or not prog_id:
        exe = _scan_windows_browser_paths(os_bins.get("chrome", []))
        if exe: return "chromium", exe, None
        return "chromium", None, "chrome"

    # Fallback: scan for any known chromium-based browser if all else fails
    for browser_name in ["comet", "brave", "chrome", "edge", "arc", "vivaldi"]:
        binaries = os_bins.get(browser_name, [])
        exe = _scan_windows_browser_paths(binaries)
        if exe:
            print(f"[Browser] Fallback found {browser_name}: {exe}")
            return "chromium", exe, None

    return "chromium", None, None


class _BrowserThread:


    def __init__(self):
        self._loop       = None
        self._thread     = None
        self._ready      = threading.Event()
        self._start_error = None
        self._playwright = None
        self._browser    = None
        self._context    = None
        self._page       = None
        self._active_backend = "playwright"
        self._force_local_browser = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._start_error = None
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BrowserThread"
        )
        self._thread.start()
        self._ready.wait(timeout=15)
        if not self._ready.is_set():
            self._start_error = RuntimeError("Browser runtime did not become ready in time.")
            raise RuntimeError("Browser runtime did not become ready in time.")
        if self._start_error is not None:
            raise RuntimeError(f"Browser runtime failed to initialize: {self._start_error}")

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._init())
        except Exception as error:
            self._start_error = error
        finally:
            self._ready.set()

        if self._start_error is not None:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None
            return

        loop.run_forever()

    async def _init(self):
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    def run(self, coro, timeout: int = 30):
        if self._start_error is not None:
            raise RuntimeError(f"Browser runtime is unavailable: {self._start_error}")
        if not self._loop:
            raise RuntimeError("BrowserThread not started.")
        if not self._loop.is_running():
            raise RuntimeError("Browser runtime loop is not running.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)
    
    async def _get_page(self):
        if self._context:
            live_pages = [page for page in self._context.pages if not page.is_closed()]
            if live_pages:
                if self._page is None or self._page.is_closed() or self._page not in live_pages:
                    self._page = live_pages[-1]
                try:
                    await self._page.bring_to_front()
                except Exception:
                    pass
                return self._page

        if self._page is None or self._page.is_closed():
            await self._launch()
        try:
            await self._page.bring_to_front()
        except Exception:
            pass
        return self._page

    async def _launch(self):
        if self._playwright is None:
            await self._init()

        lightpanda = collect_lightpanda_status()
        wants_lightpanda = not self._force_local_browser and (
            lightpanda["backend"] == "lightpanda" or lightpanda["auto_connect"]
        )

        if wants_lightpanda:
            try:
                if self._browser is None or not self._browser.is_connected():
                    self._browser = await self._playwright.chromium.connect_over_cdp(
                        lightpanda["ws_endpoint"]
                    )
                    print(f"[Browser] Connected to Lightpanda CDP at {lightpanda['ws_endpoint']}")

                contexts = list(self._browser.contexts)
                self._context = contexts[-1] if contexts else await self._browser.new_context(
                    viewport=None,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                live_pages = [page for page in self._context.pages if not page.is_closed()]
                self._page = live_pages[-1] if live_pages else await self._context.new_page()
                self._active_backend = "lightpanda"
                return
            except Exception as e:
                print(f"[Browser] Warning: Lightpanda connect failed ({e}), falling back to local browser")

        prog_id                        = _get_default_browser_id()
        # Check user's preferred browser first
        try:
            from core.user_preferences import get_browser_preference
            preferred = get_browser_preference()
            if preferred:
                preferred_lower = preferred.lower()
                print(f"[Browser] User prefers: {preferred}")
                # Inject the preferred browser into prog_id so
                # _find_browser_executable picks it up
                if preferred_lower not in prog_id.lower():
                    prog_id = preferred_lower
        except Exception:
            pass

        engine_name, exe_path, channel = _find_browser_executable(prog_id)
        engine                         = getattr(self._playwright, engine_name)

        launch_kwargs = {"headless": False}

        if engine_name == "chromium":
            launch_kwargs["args"] = ["--start-maximized"]

        if exe_path:
            launch_kwargs["executable_path"] = exe_path
        elif channel:
            launch_kwargs["channel"] = channel

        try:
            if self._browser is None or not self._browser.is_connected():
                self._browser = await engine.launch(**launch_kwargs)
                print(
                    f"[Browser] Launched ({engine_name}"
                    f"{' / ' + channel if channel else ''}"
                    f"{' / ' + exe_path if exe_path else ''})"
                )
        except Exception as e:
            print(f"[Browser] Warning: launch failed ({e}), falling back to built-in Chromium")
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=["--start-maximized"]
            )

        self._active_backend = "playwright"
        self._context = await self._browser.new_context(
            viewport=None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        self._page = await self._context.new_page()

    async def _close_browser_only(self):
        if self._page and not self._page.is_closed():
            try:
                await self._page.close()
            except Exception:
                pass
        self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

    async def _close(self):
        await self._close_browser_only()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._force_local_browser = False
        self._active_backend = "playwright"

    async def _fallback_to_local_browser(self, url: str) -> str:
        print("[Browser] Lightpanda navigation failed. Falling back to the local browser.")
        self._force_local_browser = True
        await self._close_browser_only()
        page = await self._get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        return f"Opened: {page.url} [local fallback]"

    async def _go_to(self, url: str) -> str:
        if not url.startswith("http"):
            url = "https://" + url
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return f"Opened: {page.url}"
        except PlaywrightTimeout:
            return f"Timeout loading: {url}"
        except Exception as e:
            if self._active_backend == "lightpanda" and "Target page, context or browser has been closed" in str(e):
                try:
                    return await self._fallback_to_local_browser(url)
                except Exception as fallback_error:
                    return f"Navigation error after local fallback: {fallback_error}"
            return f"Navigation error: {e}"

    async def _search(self, query: str, engine: str = "google") -> str:
        engines = {
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine.lower(), engines["google"])
        return await self._go_to(url)

    async def _click(self, selector=None, text=None) -> str:
        page = await self._get_page()
        try:
            if text:
                await page.get_by_text(text, exact=False).first.click(timeout=8000)
                return f"Clicked: '{text}'"
            elif selector:
                await page.click(selector, timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found or not clickable."
        except Exception as e:
            return f"Click error: {e}"

    async def _type(self, selector=None, text: str = "", clear_first: bool = True) -> str:
        page = await self._get_page()
        try:
            element = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await element.clear()
            await element.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def _scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def _press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def _get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4000] if len(text) > 4000 else text
        except Exception as e:
            return f"Could not get page text: {e}"

    async def _fill_form(self, fields: dict) -> str:
        page    = await self._get_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def _smart_click(self, description: str) -> str:
        page       = await self._get_page()
        desc_lower = description.lower()

        role_hints = {
            "button":    ["button", "buton", "btn"],
            "link":      ["link", "bağlantı"],
            "searchbox": ["search", "arama"],
            "textbox":   ["input", "field", "alan"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    await page.get_by_role(role).first.click(timeout=5000)
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass

        try:
            await page.get_by_text(description, exact=False).first.click(timeout=5000)
            return f"Clicked (text): '{description}'"
        except Exception:
            pass

        try:
            await page.get_by_placeholder(description, exact=False).first.click(timeout=5000)
            return f"Clicked (placeholder): '{description}'"
        except Exception:
            pass

        return f"Could not find: '{description}'"

    async def _smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()

        for method, locator in [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox")),
        ]:
            try:
                el = locator.first
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue

        return f"Could not find input: '{description}'"

    async def _close_browser(self) -> str:
        await self._close_browser_only()
        return "Browser closed."

    async def _current_state(self) -> str:
        page = await self._get_page()
        pages = [item for item in (self._context.pages if self._context else []) if not item.is_closed()]

        try:
            title = (await page.title()).strip()
        except Exception:
            title = ""

        url = str(page.url or "").strip() or "about:blank"
        lines = [
            f"Current page: {title or 'untitled'}",
            f"URL: {url}",
            f"Open tabs: {len(pages) or 1}",
        ]

        if "youtube.com" in url or "youtu.be" in url:
            try:
                state = await page.evaluate(
                    """() => {
                        const video = document.querySelector('video');
                        return {
                            isWatch: location.href.includes('/watch') || location.hostname === 'youtu.be',
                            isShort: location.href.includes('/shorts/'),
                            playing: video ? !video.paused : null,
                            currentTime: video ? Math.floor(video.currentTime || 0) : null,
                            duration: video ? Math.floor(video.duration || 0) : null
                        };
                    }"""
                )
            except Exception:
                state = {}

            if state.get("isShort"):
                lines.append("YouTube mode: shorts")
            elif state.get("isWatch"):
                lines.append("YouTube mode: video")
            elif "/results" in url:
                lines.append("YouTube mode: search results")

            if state.get("playing") is True:
                lines.append("Playback: playing")
            elif state.get("playing") is False:
                lines.append("Playback: paused")

            if state.get("currentTime") is not None and state.get("duration"):
                lines.append(f"Position: {state['currentTime']}s / {state['duration']}s")

        return "\n".join(lines)

    async def _close_tab(self) -> str:
        page = await self._get_page()
        pages = [item for item in (self._context.pages if self._context else []) if not item.is_closed()]
        if not pages:
            return "No browser tab is open."

        closing_title = ""
        try:
            closing_title = (await page.title()).strip()
        except Exception:
            closing_title = page.url

        await page.close()

        remaining = [item for item in (self._context.pages if self._context else []) if not item.is_closed()]
        if not remaining:
            self._page = None
            return f"Closed current tab: {closing_title or 'untitled'}."

        self._page = remaining[-1]
        try:
            await self._page.bring_to_front()
            next_title = (await self._page.title()).strip() or self._page.url
        except Exception:
            next_title = self._page.url

        return (
            f"Closed current tab: {closing_title or 'untitled'}.\n"
            f"Now focused: {next_title}"
        )

    async def _youtube_play(self, query: str = "", kind: str = "auto", url: str = "") -> str:
        page = await self._get_page()
        wanted_kind = _normalize_youtube_kind(query=query, requested_kind=kind)

        if str(url or "").strip():
            target_url = _normalize_youtube_href(url)
            await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            try:
                title = (await page.title()).replace(" - YouTube", "").strip()
            except Exception:
                title = ""
            actual_kind = "shorts" if _looks_like_youtube_shorts_url(page.url) else "video"
            return f"Opened YouTube {actual_kind}: {title or page.url}"

        query = str(query or "").strip()
        if not query:
            return "No YouTube query provided."

        await page.goto(_youtube_search_url(query), wait_until="domcontentloaded", timeout=20000)
        try:
            await page.wait_for_selector("a#video-title, a[href*='/shorts/']", timeout=9000)
        except Exception:
            await page.wait_for_timeout(1800)

        try:
            raw_results = await page.evaluate(
                """() => {
                    const selectors = [
                        'ytd-video-renderer a#video-title',
                        'ytd-video-renderer a#thumbnail',
                        'ytd-rich-grid-media a#video-title',
                        'ytd-rich-grid-media a#thumbnail',
                        'ytd-reel-shelf-renderer a[href*="/shorts/"]',
                        'ytd-reel-item-renderer a[href*="/shorts/"]',
                        'a#video-title',
                        'a#thumbnail'
                    ];
                    const items = [];
                    const seen = new Set();
                    for (const selector of selectors) {
                        for (const el of document.querySelectorAll(selector)) {
                            const href = (el.href || el.getAttribute('href') || '').trim();
                            if (!href || seen.has(href)) continue;
                            seen.add(href);
                            const title = (
                                el.getAttribute('title') ||
                                el.textContent ||
                                el.getAttribute('aria-label') ||
                                ''
                            ).trim();
                            const container = el.closest(
                                'ytd-video-renderer, ytd-rich-grid-media, ytd-rich-item-renderer, ytd-reel-shelf-renderer, ytd-reel-item-renderer, ytd-item-section-renderer'
                            );
                            items.push({
                                href,
                                title,
                                text: (container?.innerText || '').trim()
                            });
                        }
                    }
                    return items.slice(0, 80);
                }"""
            )
        except Exception as error:
            return f"YouTube search parsing failed: {error}"

        candidates = []
        fallback_candidates = []
        for item in raw_results or []:
            href = _normalize_youtube_href(item.get("href", ""))
            if not href or "youtube.com" not in href and "youtu.be" not in href:
                continue

            title = str(item.get("title", "") or "").strip()
            text = str(item.get("text", "") or "").strip()
            lowered = href.lower()
            is_short = _looks_like_youtube_shorts_url(lowered)
            is_watch = _looks_like_youtube_watch_url(lowered)

            entry = {
                "href": href,
                "title": title,
                "text": text,
                "is_short": is_short,
                "is_watch": is_watch,
            }
            fallback_candidates.append(entry)

            if wanted_kind == "shorts" and is_short:
                candidates.append(entry)
            elif wanted_kind == "video" and is_watch and not is_short:
                candidates.append(entry)

        if not candidates:
            if wanted_kind == "video":
                candidates = [item for item in fallback_candidates if item["is_watch"]]
            elif wanted_kind == "shorts":
                candidates = [item for item in fallback_candidates if item["is_short"]]

        if not candidates:
            return f"No suitable YouTube {wanted_kind} results found for: {query}"

        target = candidates[0]
        await page.goto(target["href"], wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(900)

        try:
            opened_title = (await page.title()).replace(" - YouTube", "").strip()
        except Exception:
            opened_title = target["title"]

        actual_kind = "shorts" if _looks_like_youtube_shorts_url(page.url.lower()) else "video"
        return f"Playing YouTube {actual_kind}: {opened_title or target['title'] or query}"

_bt         = _BrowserThread()
_bt_started = False
_bt_lock    = threading.Lock()


def _ensure_started():
    global _bt_started
    with _bt_lock:
        if not _bt_started:
            _bt.start()
            _bt_started = True


def shutdown_browser_control(timeout: int = 20) -> None:
    global _bt, _bt_started
    with _bt_lock:
        if not _bt_started or not _bt._loop:
            return
        loop = _bt._loop
        thread = _bt._thread
        try:
            _bt.run(_bt._close(), timeout=timeout)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        if thread and thread.is_alive():
            thread.join(timeout=2)
        _bt = _BrowserThread()
        _bt_started = False

def browser_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    """
    Browser controller — auto-detects and uses system default browser.

    parameters:
        action      : go_to | search | click | type | scroll | fill_form |
                      smart_click | smart_type | get_text | press | current_state |
                      close_tab | youtube_play | close
        url         : URL for go_to
        query       : search query
        engine      : google | bing | duckduckgo (default: google)
        selector    : CSS selector for click/type
        text        : text to click or type
        description : element description for smart_click/smart_type
        direction   : up | down for scroll
        amount      : scroll amount in pixels (default: 500)
        key         : key name for press (e.g. Enter, Escape, Tab)
        fields      : {selector: value} dict for fill_form
        clear_first : bool, clear input before typing (default: True)
        kind        : youtube_play only: video | shorts | auto
    """
    action = (parameters or {}).get("action", "").lower().strip()
    result = "Unknown action."

    try:
        _ensure_started()

        if action == "go_to":
            result = _bt.run(_bt._go_to(parameters.get("url", "")))

        elif action == "search":
            result = _bt.run(_bt._search(
                parameters.get("query", ""),
                parameters.get("engine", "google")
            ))

        elif action == "click":
            result = _bt.run(_bt._click(
                selector=parameters.get("selector"),
                text=parameters.get("text")
            ))

        elif action == "type":
            result = _bt.run(_bt._type(
                selector=parameters.get("selector"),
                text=parameters.get("text", ""),
                clear_first=parameters.get("clear_first", True)
            ))

        elif action == "scroll":
            result = _bt.run(_bt._scroll(
                direction=parameters.get("direction", "down"),
                amount=parameters.get("amount", 500)
            ))

        elif action == "fill_form":
            result = _bt.run(_bt._fill_form(parameters.get("fields", {})))

        elif action == "smart_click":
            result = _bt.run(_bt._smart_click(parameters.get("description", "")))

        elif action == "smart_type":
            result = _bt.run(_bt._smart_type(
                parameters.get("description", ""),
                parameters.get("text", "")
            ))

        elif action == "get_text":
            result = _bt.run(_bt._get_text())

        elif action == "press":
            result = _bt.run(_bt._press(parameters.get("key", "Enter")))

        elif action == "current_state":
            result = _bt.run(_bt._current_state())

        elif action == "close_tab":
            result = _bt.run(_bt._close_tab())

        elif action == "youtube_play":
            result = _bt.run(
                _bt._youtube_play(
                    query=parameters.get("query", ""),
                    kind=parameters.get("kind", "auto"),
                    url=parameters.get("url", ""),
                )
            )

        elif action == "close":
            result = _bt.run(_bt._close_browser())

        else:
            result = f"Unknown action: {action}"

    except concurrent.futures.TimeoutError:
        result = "Browser action timed out."
    except Exception as e:
        result = f"Browser error: {e}"

    print(f"[Browser] {result[:80]}")
    if player:
        player.write_log(f"[browser] {result[:60]}")

    return result
