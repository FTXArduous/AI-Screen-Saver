import base64
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from .slides import split_reply

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class Reply:
    text: str = ""
    images: list[Path] = field(default_factory=list)


def extract_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts)


class ApiBackend:
    """Official OpenAI Responses API. Returns the reply text."""
    name = "api"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def send(self, prompt: str) -> Optional[str]:
        body = json.dumps({"model": self.model, "input": prompt}).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return extract_text(json.load(response))


BROWSER_NAMES = ("edge", "chrome", "chromium")
BROWSER_EXECUTABLES = {
    "edge": (r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
             r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    "chrome": (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
               r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
}
DEBUG_PORT = 9222
CDP_URL = f"http://127.0.0.1:{DEBUG_PORT}"
APP_DEBUG_PORT = 9223
APP_CDP_URL = f"http://127.0.0.1:{APP_DEBUG_PORT}"
COMPOSER_SELECTOR = "#prompt-textarea"


def _cdp_running(url: str = CDP_URL) -> bool:
    try:
        urllib.request.urlopen(f"{url}/json/version", timeout=1)
        return True
    except OSError:
        return False


class WebBackend:
    """Sends prompts to chatgpt.com in a browser you can see, using Chrome DevTools Protocol.

    If a browser is already listening on DEBUG_PORT, it is attached to. Otherwise the chosen
    browser (Edge, Chrome, or Playwright's Chromium) is started with that port and its own
    profile folder under the data directory. The browser is never closed after a send, only
    the ChatGPT tab the overlay opened. Requires `pip install -e .[web]`.
    Selectors reflect the chatgpt.com UI at the time of writing and may need updating.
    """
    name = "web"

    def __init__(self, profile_root: Path, browser: str = "edge", timeout_ms: int = 120_000):
        if browser not in BROWSER_NAMES:
            raise ValueError(f"Unknown browser: {browser}")
        self.browser = browser
        self.profile_dir = (profile_root / browser).resolve()
        self.timeout_ms = timeout_ms

    def _executable(self, p) -> str:
        if self.browser == "chromium":
            path = p.chromium.executable_path
            if not Path(path).exists():
                raise RuntimeError("Playwright Chromium is not installed. Run: playwright install chromium")
            return path
        for candidate in BROWSER_EXECUTABLES[self.browser]:
            path = os.path.expandvars(candidate)
            if os.path.exists(path):
                return path
        raise RuntimeError(f"{self.browser} was not found on this computer.")

    def _connect(self, p):
        if not _cdp_running():
            exe = self._executable(p)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            subprocess.Popen([exe, f"--remote-debugging-port={DEBUG_PORT}",
                              f"--user-data-dir={self.profile_dir}", "--no-first-run",
                              "--disable-extensions", "--disable-component-extensions-with-background-pages"])
            deadline = time.monotonic() + 30
            while not _cdp_running():
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{self.browser} did not open its debugging port in time.")
                time.sleep(0.5)
        return p.chromium.connect_over_cdp(CDP_URL)

    @staticmethod
    def _new_page(browser):
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        return context.new_page()

    def open_for_login(self, wait_ms: int = 600_000) -> str:
        """Open chatgpt.com in the browser and wait until the prompt box appears (you log in there)."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = self._connect(p)
            page = self._new_page(browser)
            try:
                page.goto("https://chatgpt.com/")
                page.locator(COMPOSER_SELECTOR).wait_for(timeout=wait_ms)
                return f"Logged in to ChatGPT in {self.browser}."
            finally:
                page.close()

    def send(self, prompt: str) -> Optional[str]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = self._connect(p)
            page = self._new_page(browser)
            try:
                page.goto("https://chatgpt.com/")
                box = page.locator(COMPOSER_SELECTOR)
                try:
                    box.wait_for(timeout=self.timeout_ms)
                except Exception as exc:
                    raise RuntimeError("ChatGPT prompt box not found. Use 'Log in to ChatGPT (web)' "
                                       "from the menu first.") from exc
                box.fill(prompt)
                page.locator('button[data-testid="send-button"]').click()
                page.locator('button[data-testid="stop-button"]').wait_for(timeout=self.timeout_ms)
                page.locator('button[data-testid="stop-button"]').wait_for(state="detached", timeout=self.timeout_ms)
                replies = page.locator('[data-message-author-role="assistant"]')
                return replies.last.inner_text()
            finally:
                page.close()


TAB_BROWSER_FLAGS = (
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion",
    "--no-first-run",
    "--disable-extensions",
)


def _start_debug_browser(browser: str, profile_dir: Path) -> None:
    """Start Edge or Chrome on chatgpt.com with the debugging port and its own profile, unless it is already up."""
    if _cdp_running():
        return
    exe = None
    for candidate in BROWSER_EXECUTABLES[browser]:
        path = os.path.expandvars(candidate)
        if os.path.exists(path):
            exe = path
            break
    if exe is None:
        raise RuntimeError(f"{browser} was not found on this computer.")
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile_dir}",
                      *TAB_BROWSER_FLAGS, "https://chatgpt.com"])
    deadline = time.monotonic() + 30
    while not _cdp_running():
        if time.monotonic() > deadline:
            raise RuntimeError(f"{browser} did not open its debugging port in time.")
        time.sleep(0.5)


class TabBackend:
    """Sends and reads through a chatgpt.com tab in an Edge or Chrome the overlay starts itself.

    The browser uses its own profile under the data directory, so your normal windows are left alone.
    Sign in to ChatGPT once in the window that opens. Chrome DevTools Protocol works without window focus,
    so the overlay can stay fullscreen on top while replies are read in the background.
    Requires `pip install -e .[web]`.
    """
    name = "tab"

    def __init__(self, profile_root: Path, browser: str = "edge"):
        if browser not in BROWSER_EXECUTABLES:
            raise ValueError(f"Unknown browser: {browser}")
        self.browser = browser
        self.profile_dir = (profile_root / browser).resolve()

    def _ensure_browser(self) -> None:
        _start_debug_browser(self.browser, self.profile_dir)

    def _connect(self, p):
        return p.chromium.connect_over_cdp(CDP_URL)

    def _find_page(self, browser):
        return _chatgpt_tab(browser)

    def _find_open_page(self, browser):
        return _chatgpt_tab(browser, create=False)

    def send(self, prompt: str, image_dir: Optional[Path] = None,
             cancel: Optional[threading.Event] = None,
             status: Optional[Callable[[str], None]] = None,
             partial: Optional[Callable[[Reply], None]] = None) -> Reply:
        """Send the prompt and return the reply once its text and any image have finished.

        `partial` receives new text chunks and newly saved images while ChatGPT is still writing or rendering.
        The returned Reply then holds only what was not already passed to `partial`.
        """
        from playwright.sync_api import sync_playwright

        say = status or (lambda _text: None)
        say("Starting the browser for ChatGPT...")
        self._ensure_browser()
        with sync_playwright() as p:
            browser = self._connect(p)
            page = self._find_page(browser)
            _keep_tab_live(page)
            _wait_for_tab_idle(page, cancel)
            seen = _turn_keys(page)
            say("Sending the question to ChatGPT...")
            _submit_prompt(page, prompt)
            sent_at = time.monotonic()
            say("ChatGPT is replying...")
            deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
            resent = False
            phase = ""
            render_started = None
            current = ""
            emitted_chunks = 0
            image_srcs: set = set()
            quiet_polls = 0
            last_state = None
            state_since = time.monotonic()
            last_progress = None
            last_progress_at = time.monotonic()
            reconnected = False
            key = None
            while True:
                _pause(POLL_SECONDS, cancel)
                _scroll_tab_to_bottom(page)
                _dismiss_prompts(page)
                working = _is_generating(page)
                prompt_found, found_key = _find_reply_key(page, prompt, seen)
                if found_key:
                    key = found_key
                has_data = False
                has_images = False
                rendering = False
                if key:
                    reply = _reply_locator(page, key)
                    turn = _reply_turn_locator(page, key)
                    current = _reply_text(reply)
                    rendering = _is_rendering_image(turn)
                    if rendering and render_started is None:
                        render_started = time.monotonic()
                    elif not rendering:
                        render_started = None
                    # A reply still drawing an image has no text yet, so the image slot counts as data.
                    has_images = turn.locator("img").count() > 0
                    has_data = bool(current) or rendering or has_images
                    # The reply must stay unchanged for a few polls, so an image slot that has not appeared yet is not missed.
                    state = (current, has_images, rendering)
                    quiet_polls = quiet_polls + 1 if state == last_state else 0
                    if state != last_state:
                        state_since = time.monotonic()
                        reconnected = False
                    last_state = state
                    # Finished means every image has loaded and none is still rendering, and the reply has stopped changing.
                    # A Stop control can stay on screen after ChatGPT is done, so an unchanged reply also counts as finished.
                    render_done = not rendering or time.monotonic() - render_started >= IMAGE_WAIT_SECONDS
                    stable = reconnected or not working or time.monotonic() - state_since >= STABLE_FINISH_SECONDS
                    finished = (has_data and render_done and (quiet_polls >= QUIET_POLLS or reconnected) and stable
                                and _images_loaded(turn) and (current or has_images))
                    if partial:
                        # The last chunk may still be growing, so it is held back until the reply is finished.
                        chunks = split_reply(current)
                        ready = chunks if finished else chunks[:-1]
                        new_text = ready[emitted_chunks:]
                        emitted_chunks = max(emitted_chunks, len(ready))
                        new_images = (_save_tab_images(page, turn, image_dir, say, skip=image_srcs)
                                      if image_dir and _has_big_image(turn) else [])
                        if new_text or new_images:
                            partial(Reply(text="\n\n".join(new_text), images=new_images))
                    if finished:
                        break
                # Re-send at most once per question, and only when the question itself never landed on the page.
                if (not prompt_found and not key and not working and not resent
                        and time.monotonic() - sent_at >= NO_REPLY_RETRY_SECONDS):
                    say("No reply after 15 s. Sending the question again...")
                    _submit_prompt(page, prompt)
                    sent_at = time.monotonic()
                    resent = True
                    continue
                if rendering:
                    now_phase = "rendering"
                elif has_data and current:
                    now_phase = "writing"
                elif working:
                    now_phase = "thinking"
                else:
                    now_phase = "waiting"
                if now_phase != phase:
                    phase = now_phase
                    say({"rendering": "ChatGPT is rendering an image...",
                         "writing": "ChatGPT is writing...",
                         "thinking": "ChatGPT is thinking...",
                         "waiting": "ChatGPT is replying..."}[phase])
                progress = (current, has_images, rendering, phase)
                if progress != last_progress:
                    last_progress = progress
                    last_progress_at = time.monotonic()
                elif time.monotonic() - last_progress_at >= STALL_SECONDS:
                    # Reconnect only. The prompt is never sent again, so a stall cannot cause a second question.
                    say("ChatGPT has not changed for 10 s. Reconnecting to the tab...")
                    # Attach again to the existing tab only. The browser is never closed and no tab is opened.
                    try:
                        browser = self._connect(p)
                        page = self._find_open_page(browser)
                    except Exception:
                        say("Could not reconnect yet. Still watching the ChatGPT tab...")
                        last_progress_at = time.monotonic()
                    else:
                        _keep_tab_live(page)
                        last_progress_at = time.monotonic()
                        # The reply already on the page is complete as far as the screen shows, so it is finished now.
                        reconnected = True
                if time.monotonic() > deadline:
                    raise RuntimeError("ChatGPT did not finish replying in time.")
            say("ChatGPT finished. Reading the full reply...")
            _scroll_tab_to_bottom(page)
            _, final_key = _find_reply_key(page, prompt, seen)
            final_key = final_key or key
            full_text = _reply_text(_reply_locator(page, final_key))
            text = "\n\n".join(split_reply(full_text)[emitted_chunks:]) if partial else full_text
            images = (_save_tab_images(page, _reply_turn_locator(page, final_key), image_dir, say,
                                       skip=image_srcs) if image_dir else [])
            return Reply(text=text, images=images)


ASSISTANT_LABEL = "ChatGPT said:"
TAB_COMPOSER_SELECTOR = 'div[contenteditable="true"][role="textbox"]'
NO_REPLY_RETRY_SECONDS = 15
QUIET_POLLS = 3
POLL_SECONDS = 1
STABLE_FINISH_SECONDS = 6
STALL_SECONDS = 10
IMAGE_WAIT_SECONDS = 180
IMAGE_MIN_WIDTH = 200
IMAGE_MIN_HEIGHT = 120


def _turn_keys(page) -> set:
    """Identifiers of every question and reply already on the page, so only new ones count."""
    return set(page.evaluate("""() => [...new Set([...document.querySelectorAll('[data-chatgpt-search-unit-key]')]
        .map(e => e.getAttribute('data-chatgpt-search-unit-key')))]"""))


def _find_reply_key(page, prompt: str, seen: set) -> tuple[bool, Optional[str]]:
    """Find this question's block (matched by its text, newer than `seen`) and the reply block that follows it.

    Returns (question_found, reply_key). The reply is the first new assistant block after the question in page
    order. If the question text can't be found, the newest new assistant block is used instead.
    """
    needle = " ".join(prompt.split())[:80]
    result = page.evaluate("""([needle, seen]) => {
        const norm = s => s.replace(/\\s+/g, ' ').trim();
        const blocks = [...document.querySelectorAll('[data-chatgpt-search-unit-key]')]
            .map(e => ({key: e.getAttribute('data-chatgpt-search-unit-key'), text: e.textContent}))
            .filter(b => !seen.includes(b.key));
        let questionIndex = -1;
        blocks.forEach((b, i) => {
            if (!b.text.includes('ChatGPT said:') && norm(b.text).includes(needle)) questionIndex = i;
        });
        const replies = blocks.map((b, i) => ({...b, i})).filter(b => b.text.includes('ChatGPT said:'));
        let reply = null;
        if (questionIndex >= 0) {
            reply = replies.find(b => b.i > questionIndex) || null;
        } else if (replies.length) {
            reply = replies[replies.length - 1];
        }
        return {question: questionIndex >= 0, reply: reply ? reply.key : null};
    }""", [needle, list(seen)])
    return bool(result["question"]), result["reply"]


def _reply_locator(page, key: Optional[str]):
    return page.locator(f'[data-chatgpt-search-unit-key="{key}"]').filter(has_text=ASSISTANT_LABEL).last


def _reply_turn_locator(page, key: Optional[str]):
    """The whole exchange holding the reply, so images rendered outside the text block are included."""
    return page.locator(f'[data-turn-key]:has([data-chatgpt-search-unit-key="{key}"])').last


def _submit_prompt(page, prompt: str) -> None:
    """Replace whatever is in the composer with the prompt and send it."""
    page.locator(TAB_COMPOSER_SELECTOR).first.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(prompt)
    page.keyboard.press("Enter")


def _chatgpt_tab(browser, create: bool = True):
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith("https://chatgpt.com"):
                return page
    if not create:
        raise RuntimeError("No ChatGPT tab is open in the browser.")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    page.goto("https://chatgpt.com", wait_until="domcontentloaded")
    page.locator(TAB_COMPOSER_SELECTOR).first.wait_for(timeout=120_000)
    return page


def _keep_tab_live(page) -> None:
    """Make the tab behave as focused while the overlay covers it, so ChatGPT keeps rendering and streaming."""
    try:
        session = page.context.new_cdp_session(page)
        session.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
    except Exception:
        pass


def _scroll_tab_to_bottom(page) -> None:
    """Scroll the newest message and every scrollable ancestor to the bottom, so the page keeps rendering."""
    try:
        page.evaluate("""() => {
            const messages = [...document.querySelectorAll('[data-chatgpt-search-unit-key]')]
                .filter(e => e.textContent.includes('ChatGPT said:'));
            const last = messages[messages.length - 1];
            if (last) last.scrollIntoView({block: 'end'});
            for (let el = last; el; el = el.parentElement) {
                if (el.scrollHeight > el.clientHeight + 5) el.scrollTop = el.scrollHeight;
            }
            window.scrollTo(0, document.body.scrollHeight);
        }""")
    except Exception:
        pass


def _dismiss_prompts(page) -> None:
    """Click ChatGPT's "Keep thinking" prompt, OK dialogs, and "Try again" on a failed reply so the run keeps going."""
    try:
        page.evaluate("""() => {
            const labelOf = b => (b.innerText || b.getAttribute('aria-label') || '').trim();
            for (const b of document.querySelectorAll('button')) {
                if (/^keep thinking$/i.test(labelOf(b))) { b.click(); return; }
            }
            for (const b of document.querySelectorAll('[role="dialog"] button')) {
                if (/^ok$/i.test(labelOf(b))) { b.click(); return; }
            }
            for (const b of document.querySelectorAll('button')) {
                if (/^(try again|retry)$/i.test(labelOf(b)) && b.closest('[data-turn-key]') && b.offsetParent !== null) {
                    b.click(); return;
                }
            }
        }""")
    except Exception:
        pass


def _reply_text(message) -> str:
    """The reply's visible text without ChatGPT's hidden "ChatGPT said:" label."""
    text = message.inner_text().strip()
    return text[len(ASSISTANT_LABEL):].strip() if text.startswith(ASSISTANT_LABEL) else text


def _is_generating(page) -> bool:
    """True while ChatGPT shows a Stop control, which it does only while a reply is still being written."""
    try:
        return bool(page.evaluate("""() => [...document.querySelectorAll('button')].some(b => {
            const label = (b.getAttribute('aria-label') || '') + ' ' + (b.getAttribute('data-testid') || '');
            const text = (b.innerText || '').trim();
            return (/\\bstop\\b|stop-button/i.test(label) || /^stop$/i.test(text)) && b.offsetParent !== null;
        })"""))
    except Exception:
        return True


def _images_loaded(message) -> bool:
    return message.locator("img").evaluate_all("els => els.every(e => e.complete)")


def _is_rendering_image(message) -> bool:
    """True while ChatGPT is still drawing an image: an image is loading, an image slot has no large image yet,
    or a "creating an image" placeholder is shown with no large image yet."""
    return message.evaluate("""(el) => {
        const imgs = [...el.querySelectorAll('img')];
        const slots = el.querySelectorAll('[data-testid*="generated-image"]').length;
        const loaded = imgs.some(i => i.complete && i.naturalWidth >= 200 && i.naturalHeight >= 120);
        const placeholder = /(creating|generating|rendering|drawing) (an? )?image/i.test(el.textContent);
        return imgs.some(i => !i.complete) || (slots > 0 && !loaded) || (!loaded && placeholder);
    }""")


def _has_big_image(message) -> bool:
    """True once the reply holds at least one large, fully loaded image."""
    return message.locator("img").evaluate_all(
        "(els, [w, h]) => els.some(e => e.complete && e.naturalWidth >= w && e.naturalHeight >= h)",
        [IMAGE_MIN_WIDTH, IMAGE_MIN_HEIGHT])


def _wait_for_tab_idle(page, cancel: Optional[threading.Event]) -> None:
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    while _is_generating(page):
        if time.monotonic() > deadline:
            raise RuntimeError("ChatGPT is still generating an earlier reply.")
        _dismiss_prompts(page)
        _pause(2, cancel)


def _save_tab_images(page, message, image_dir: Path, say: Callable[[str], None],
                     min_width: int = IMAGE_MIN_WIDTH, min_height: int = IMAGE_MIN_HEIGHT,
                     skip: Optional[set] = None) -> list[Path]:
    """Save the large images in the latest reply as PNG files, read through the page itself (blob: URLs need it).

    Sources already in `skip` are left out; saved sources are added to it, so repeated calls return only new images.
    """
    infos = message.locator("img").evaluate_all(
        "els => els.map(e => ({src: e.currentSrc || e.src, w: e.naturalWidth, h: e.naturalHeight}))")
    seen_src = skip if skip is not None else set()
    big = []
    for index, info in enumerate(infos):
        if info["w"] >= min_width and info["h"] >= min_height and info["src"] not in seen_src:
            seen_src.add(info["src"])
            big.append((index, info))
    if not big:
        return []
    image_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    for number, (index, info) in enumerate(big, 1):
        say(f"Saving image {number} of {len(big)} from ChatGPT...")
        path = image_dir / f"chatgpt-image-{stamp}-{number}.png"
        try:
            data_url = page.evaluate("""async (src) => {
                const blob = await (await fetch(src)).blob();
                return await new Promise((ok, fail) => {
                    const reader = new FileReader();
                    reader.onload = () => ok(reader.result);
                    reader.onerror = fail;
                    reader.readAsDataURL(blob);
                });
            }""", info["src"])
            data = base64.b64decode(data_url.split(",", 1)[1])
            Image.open(io.BytesIO(data)).convert("RGB").save(path)
        except Exception:
            message.locator("img").nth(index).screenshot(path=str(path))
        paths.append(path)
    return paths


def _find_app_exe() -> Optional[str]:
    """The ChatGPT desktop app's executable, found through its Store package, or None."""
    command = "(Get-AppxPackage -Name 'OpenAI.Codex' | Select-Object -First 1).InstallLocation"
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    location = result.stdout.strip()
    exe = Path(location) / "app" / "ChatGPT.exe"
    return str(exe) if location and exe.is_file() else None


def _app_page(browser):
    """The ChatGPT app's main page, which has a composer. The app is never navigated to another URL."""
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith("app://") and page.locator(TAB_COMPOSER_SELECTOR).count() > 0:
                return page
    raise RuntimeError("Open a chat in the ChatGPT app window that the overlay started, then try again.")


class AppBackend(TabBackend):
    """Sends and reads through the ChatGPT desktop app, started by the overlay with its own profile and debug port.

    The app runs in a separate profile under the data directory, so the app you already use is not touched.
    Sign in once in the window that opens. Reply reading uses the same page selectors as the tab backend,
    which have not been verified against a desktop chat yet.
    Requires `pip install -e .[web]`.
    """
    name = "app"

    def __init__(self, profile_root: Path):
        self.browser = "app"
        self.profile_dir = (profile_root / "desktop-app").resolve()

    def _ensure_browser(self) -> None:
        if _cdp_running(APP_CDP_URL):
            return
        exe = _find_app_exe()
        if exe is None:
            raise RuntimeError("The ChatGPT desktop app was not found on this computer.")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([exe, f"--remote-debugging-port={APP_DEBUG_PORT}", f"--user-data-dir={self.profile_dir}"])
        deadline = time.monotonic() + 30
        while not _cdp_running(APP_CDP_URL):
            if time.monotonic() > deadline:
                raise RuntimeError("The ChatGPT app did not open its debugging port in time.")
            time.sleep(0.5)

    def _connect(self, p):
        return p.chromium.connect_over_cdp(APP_CDP_URL)

    def _find_page(self, browser):
        return _app_page(browser)

    def _find_open_page(self, browser):
        return _app_page(browser)


class DesktopBackend:
    """Types into the ChatGPT Windows desktop app via UI Automation. Requires `pip install -e .[desktop]`.

    Replies are not read back, so this backend returns None.
    """
    name = "desktop"

    def send(self, prompt: str) -> Optional[str]:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(title_re=".*ChatGPT.*")
        window.set_focus()
        edit = window.child_window(control_type="Edit", found_index=0)
        edit.set_edit_text(prompt)
        edit.type_keys("{ENTER}", with_spaces=True)
        return None


BROWSER_WINDOW_PATTERN = re.compile(r"(Microsoft\u200b? Edge|Google Chrome)$")


def _address_bar_url(window) -> str:
    for edit in window.descendants(control_type="Edit"):
        if "address" in (edit.element_info.name or "").lower():
            return edit.get_value() or ""
    return ""


def _shows_chatgpt(window) -> bool:
    return "chatgpt.com" in _address_bar_url(window)


def _find_chatgpt_window(max_tab_presses: int = 40):
    from pywinauto import Desktop

    windows = [w for w in Desktop(backend="uia").windows() if BROWSER_WINDOW_PATTERN.search(w.window_text())]
    for window in windows:
        if _shows_chatgpt(window):
            return window
    for window in windows:
        window.set_focus()
        for _ in range(max_tab_presses):
            window.type_keys("^{TAB}", pause=0.05)
            time.sleep(0.2)
            if _shows_chatgpt(window):
                return window
    raise RuntimeError("No Edge or Chrome tab showing chatgpt.com was found in the open browser windows.")


def _find_prompt_box(window, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.set_focus()
        for edit in window.descendants(control_type="Edit"):
            name = edit.element_info.name or ""
            if "address" not in name.lower() and re.search(r"ask|message|chatgpt", name, re.I):
                return edit
        time.sleep(0.5)
    raise RuntimeError("Found chatgpt.com, but its prompt box did not appear. Is the page signed in?")


REPLY_TIMEOUT_SECONDS = 600


class SendCancelled(RuntimeError):
    """Raised when automation is stopped while a send is in progress."""


def _pause(seconds: float, cancel: Optional[threading.Event] = None) -> None:
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise SendCancelled("Automation stopped.")


def _dismiss_window_prompts(window) -> None:
    """Click ChatGPT's 'Keep thinking' or OK prompts so a long reply doesn't stall."""
    for button in window.descendants(control_type="Button"):
        name = (button.element_info.name or "").strip().lower()
        if name == "ok" or "keep thinking" in name:
            try:
                button.invoke()
            except Exception:
                pass


def _wait_until_idle(window, cancel: Optional[threading.Event] = None) -> None:
    """Wait until ChatGPT is no longer generating an earlier reply, so a new prompt isn't typed over it."""
    deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
    while _is_streaming(window):
        if time.monotonic() > deadline:
            raise RuntimeError("ChatGPT is still generating an earlier reply.")
        _dismiss_window_prompts(window)
        _pause(2, cancel)


def _write_clipboard(text: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "[Console]::InputEncoding=[Text.Encoding]::UTF8; $input | Set-Clipboard"],
                   input=text.encode("utf-8"), check=True)


def _read_clipboard() -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
                             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                            capture_output=True, check=True)
    return result.stdout.decode("utf-8", errors="replace").strip()


def _copy_buttons(window) -> list:
    """ChatGPT's per-reply Copy buttons, in page order. Code-block and user-message buttons are named differently."""
    return [b for b in window.descendants(control_type="Button") if b.element_info.name == "Copy"]


def _is_streaming(window) -> bool:
    return any("stop" in (b.element_info.name or "").lower()
               for b in window.descendants(control_type="Button"))


def _scroll_to_bottom(window) -> None:
    for group in window.descendants(control_type="Group"):
        if group.element_info.name == "Conversation":
            group.iface_scroll.SetScrollPercent(-1, 100.0)
            time.sleep(1.0)
            return


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _download_image(window, image, out_dir: Path, name: str, timeout: float = 20.0) -> Optional[Path]:
    """Click the image's Download button and copy the new file out of the Downloads folder.

    Returns None when ChatGPT exposes no Download button for the image, so the caller can fall back.
    """
    rect = image.rectangle()
    buttons = [b for b in window.descendants(control_type="Button")
               if "download" in (b.element_info.name or "").lower()
               and rect.left - 10 <= b.rectangle().left <= rect.right + 10
               and rect.top - 10 <= b.rectangle().top <= rect.bottom + 10]
    if not buttons:
        return None
    downloads = Path.home() / "Downloads"
    before = set(downloads.iterdir()) if downloads.exists() else set()
    buttons[0].invoke()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new = [p for p in downloads.iterdir()
               if p not in before and p.suffix.lower() in IMAGE_SUFFIXES] if downloads.exists() else []
        if new:
            source = max(new, key=lambda p: p.stat().st_mtime)
            target = out_dir / f"{name}{source.suffix.lower()}"
            shutil.copy2(source, target)
            return target
        time.sleep(0.5)
    return None


def _capture_reply_images(window, out_dir: Path, min_width: int = 200, min_height: int = 120,
                          status: Optional[Callable[[str], None]] = None) -> list[Path]:
    """Save large images that sit between the latest 'ChatGPT said:' label and its Copy button.

    Each image is downloaded through its Download button when ChatGPT offers one. Otherwise it is
    captured from the screen.
    """
    said = [t for t in window.descendants(control_type="Text") if t.element_info.name == "ChatGPT said:"]
    copies = _copy_buttons(window)
    if not said or not copies:
        return []
    top = said[-1].rectangle().top
    bottom = copies[-1].rectangle().top
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    images = [i for i in window.descendants(control_type="Image")
              if i.rectangle().width() >= min_width and i.rectangle().height() >= min_height
              and top <= i.rectangle().top and i.rectangle().bottom <= bottom]
    paths = []
    for number, image in enumerate(images, 1):
        if status:
            status(f"Saving image {number} of {len(images)} from ChatGPT...")
        name = f"chatgpt-image-{stamp}-{number}"
        path = _download_image(window, image, out_dir, name)
        if path is None:
            path = out_dir / f"{name}.png"
            image.capture_as_image().save(path)
        paths.append(path)
    return paths


def _wait_for_reply(window, baseline: int, timeout: float = REPLY_TIMEOUT_SECONDS,
                    cancel: Optional[threading.Event] = None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _pause(2, cancel)
        _dismiss_window_prompts(window)
        buttons = _copy_buttons(window)
        if len(buttons) > baseline and not _is_streaming(window):
            return buttons[-1]
    raise RuntimeError("ChatGPT did not finish replying in time.")


def _copy_reply(button, timeout: float = 5.0) -> str:
    marker = f"ushi-copy-{uuid.uuid4().hex}"
    _write_clipboard(marker)
    button.invoke()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = _read_clipboard()
        if text and text != marker:
            return text
        time.sleep(0.2)
    raise RuntimeError("Copying the ChatGPT reply did not work.")


class WindowBackend:
    """Types into the chatgpt.com tab of an Edge or Chrome window you already have open.

    Nothing is launched or attached. The tab is found by its address bar URL (Ctrl+Tab cycles tabs
    until chatgpt.com is found), then the prompt box is located through UI Automation. The prompt is
    pasted through the clipboard and sent with Enter. After the reply finishes, the conversation is
    scrolled to the bottom, the reply text is copied with its Copy button, and any generated images are
    captured. `hooks` (hide, show) are called around the capture so the overlay doesn't cover the chat.
    Requires `pip install -e .[desktop]`.
    """
    name = "window"

    def send(self, prompt: str, hooks: Optional[tuple[Callable[[], None], Callable[[], None]]] = None,
             image_dir: Optional[Path] = None, cancel: Optional[threading.Event] = None,
             status: Optional[Callable[[str], None]] = None) -> Reply:
        say = status or (lambda _text: None)
        say("Finding the ChatGPT tab...")
        window = _find_chatgpt_window()
        _wait_until_idle(window, cancel)
        composer = _find_prompt_box(window)
        composer.click_input()
        say("Sending the question to ChatGPT...")
        _write_clipboard(prompt)
        window.type_keys("^v", pause=0.05)
        baseline = len(_copy_buttons(window))
        _pause(0, cancel)
        window.type_keys("{ENTER}", pause=0.05)
        say("ChatGPT is replying...")
        copy_button = _wait_for_reply(window, baseline, cancel=cancel)
        say("ChatGPT finished. Reading the full reply...")
        _dismiss_window_prompts(window)
        _scroll_to_bottom(window)
        copy_button = _copy_buttons(window)[-1]
        text = _copy_reply(copy_button)
        images: list[Path] = []
        if hooks and image_dir:
            _pause(0, cancel)
            hide, show = hooks
            hide()
            try:
                window.set_focus()
                time.sleep(0.5)
                images = _capture_reply_images(window, image_dir, status=say)
            finally:
                show()
        return Reply(text=text, images=images)
