import queue
import random
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import simpledialog

from PIL import Image, ImageTk

from .backends import ApiBackend, BROWSER_NAMES, DesktopBackend, Reply, SendCancelled, TabBackend, WebBackend, WindowBackend
from .engine import ArrowPath, IdleTracker, interval_seconds, ALLOWED_INTERVAL_MINUTES
from .keystore import get_api_key, set_api_key
from .questions import QUESTION_COUNT, engine_question
from .slides import render_slides, render_text_card, split_reply

FRAME_MS = 16
SLIDE_SECONDS = 2
OVERLAY_SECONDS = 2
ITEM_SECONDS = 4.8
NEXT_SEND_MS = 2000
BACKEND_NAMES = ("api", "web", "desktop", "window", "tab")


class Overlay:
    def __init__(self, data_dir: Path, backend: str = "api", interval_minutes: int = 3):
        self.data_dir = data_dir
        self.backend_name = backend
        self.browser = "edge"
        self.interval_minutes = interval_minutes
        self.running = False
        self.chrome_hidden = False
        self.revealed = False

        self.results: queue.Queue = queue.Queue()
        self.ui_calls: queue.Queue = queue.Queue()
        self.display_queue: queue.Queue = queue.Queue()
        self.run_cancel = threading.Event()
        self._was_fullscreen = True
        self.busy = False
        self.idle = IdleTracker()
        self._timer = None
        self.slides: list[Path] = []
        self.slide_index = -1
        self.showing_slide = False
        self.showing_reply = False
        self.waiting_for_slides = False
        self.phase_until = time.monotonic() + OVERLAY_SECONDS
        self._slide_photo = None
        self._reply_photo = None
        threading.Thread(target=self._load_slides, daemon=True).start()

        self.root = tk.Tk()
        self.root.title("Milkyway Mapper ScreenSaver")
        self.root.configure(bg="black")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.bind("<Motion>", lambda _e: self.idle.activity())
        self.root.bind("<Button>", lambda _e: self.idle.activity())
        self.root.bind("<Escape>", lambda _e: self._on_escape())
        self.root.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<Control-q>", lambda _e: self.quit())
        self.root.bind("<Key-1>", self._on_key_one)
        self.root.bind("<F5>", lambda _e: self.toggle_running())

        self.arrow = tk.Label(self.root, text="\u25bc", bg="#222222", fg="white",
                              font=("Segoe UI", 8), cursor="hand2")
        self.arrow.bind("<Button-1>", lambda _e: self._show_menu())

        self.editor = tk.Frame(self.root, bg="black")
        self.prompt_text = tk.Text(self.editor, height=4, width=70, bg="#111111", fg="white",
                                   insertbackground="white", wrap="word")
        self.prompt_text.pack()

        self.status_label = tk.Label(self.root, text="", bg="black", fg="#aaaaaa", wraplength=1200,
                                     justify="center", font=("Segoe UI", 11))
        self.status_label.place(relx=0.5, rely=1.0, anchor="s", y=-50)

        self.slide_label = tk.Label(self.root, bg="black", bd=0)
        self.path = ArrowPath(width=self.root.winfo_screenwidth())
        self.menu = tk.Menu(self.root, tearoff=0)
        self._build_menu()
        self._place_chrome()
        self._tick()

    def _build_menu(self):
        self.menu.delete(0, "end")
        self.menu.add_command(label="Start automation" if not self.running else "Stop automation",
                              command=self.toggle_running)
        backend_menu = tk.Menu(self.menu, tearoff=0)
        backend_var = tk.StringVar(value=self.backend_name)
        for name in BACKEND_NAMES:
            backend_menu.add_radiobutton(label=name, value=name, variable=backend_var,
                                         command=lambda n=name: self.set_backend(n))
        self.menu.add_cascade(label="Backend", menu=backend_menu)
        browser_menu = tk.Menu(self.menu, tearoff=0)
        browser_var = tk.StringVar(value=self.browser)
        for name in BROWSER_NAMES:
            browser_menu.add_radiobutton(label=name, value=name, variable=browser_var,
                                         command=lambda n=name: self.set_browser(n))
        self.menu.add_cascade(label="Web browser", menu=browser_menu)
        self.menu.add_command(label="Log in to ChatGPT (web)...", command=self.login_web)
        interval_menu = tk.Menu(self.menu, tearoff=0)
        for minutes in ALLOWED_INTERVAL_MINUTES:
            interval_menu.add_command(label=f"{minutes} min", command=lambda m=minutes: self.set_interval(m))
        self.menu.add_cascade(label="Interval", menu=interval_menu)
        self.menu.add_command(label="Set OpenAI API key...", command=self.set_api_key_dialog)
        self.menu.add_separator()
        self.menu.add_command(label="Toggle fullscreen (Esc / F11)", command=self.toggle_fullscreen)
        self.menu.add_command(label="Quit (Ctrl+Q)", command=self.quit)

    def _show_menu(self):
        self._build_menu()
        self.menu.tk_popup(self.arrow.winfo_rootx(), self.arrow.winfo_rooty() - 4)

    def _place_chrome(self):
        visible = not self.chrome_hidden
        if visible:
            self.arrow.place(x=int(self.path.x), y=self.root.winfo_height() - 24, width=20, height=20)
            self.editor.place(relx=0.5, rely=1.0, anchor="s", y=-30)
        else:
            self.arrow.place_forget()
            self.editor.place_forget()

    def set_backend(self, name: str):
        self.backend_name = name
        self.status_label.config(text=f"Backend: {name}")

    def set_browser(self, name: str):
        self.browser = name
        self.status_label.config(text=f"Web browser: {name}")

    def login_web(self):
        if self.busy:
            self.status_label.config(text="Busy; try again in a moment.")
            return
        self.busy = True
        self.status_label.config(text=f"Opening {self.browser} for ChatGPT login. Log in there; this waits up to 10 minutes.")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self):
        try:
            backend = WebBackend(self.data_dir / "web-profile", browser=self.browser)
            self.results.put(("ok", backend.open_for_login(), None))
        except Exception as exc:
            self.results.put(("error", f"Login error: {exc}", None))

    def _on_key_one(self, event):
        if event.widget is self.prompt_text:
            return
        self.toggle_running()

    def set_interval(self, minutes: int):
        self.interval_minutes = minutes

    def set_api_key_dialog(self):
        key = simpledialog.askstring("OpenAI API key", "Enter API key (stored in Windows Credential Manager):",
                                     show="*", parent=self.root)
        if key:
            set_api_key(key.strip())
            self.status_label.config(text="API key saved.")

    def _on_escape(self):
        self.toggle_fullscreen()
        if self.running:
            self.revealed = not self.root.attributes("-fullscreen")
            self.chrome_hidden = not self.revealed
            self._place_chrome()
            if self.revealed:
                self.idle.activity()

    def toggle_running(self):
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        self.running = True
        self.run_cancel = threading.Event()
        self.chrome_hidden = True
        self.revealed = False
        self._place_chrome()
        self._continue_loop(0)

    def _stop(self):
        self.running = False
        self.run_cancel.set()
        self.revealed = False
        if self._timer is not None:
            self.root.after_cancel(self._timer)
            self._timer = None
        self._clear_items()
        self.waiting_for_slides = False
        if self.showing_reply:
            self.showing_reply = False
            self.slide_label.place_forget()
        self.chrome_hidden = False
        self._place_chrome()

    def _continue_loop(self, delay_ms: int):
        """Schedule the next question. Only one timer is pending at a time."""
        if not self.running:
            return
        if self._timer is not None:
            self.root.after_cancel(self._timer)
        self._timer = self.root.after(delay_ms, self._fire)

    def _build_backend(self):
        if self.backend_name == "web":
            return WebBackend(self.data_dir / "web-profile", browser=self.browser)
        if self.backend_name == "desktop":
            return DesktopBackend()
        if self.backend_name == "window":
            return WindowBackend()
        if self.backend_name == "tab":
            return TabBackend(self.data_dir / "tab-profile", browser=self.browser)
        key = get_api_key()
        if not key:
            raise RuntimeError("No OpenAI API key saved. Use 'Set OpenAI API key...' first.")
        return ApiBackend(key)

    def _fire(self):
        self._timer = None
        if not self.running:
            return
        self._send_now()

    def _send_now(self):
        if not self.running:
            return
        if self.busy:
            self.status_label.config(text="Waiting for the previous request to finish...")
            self._continue_loop(500)
            return
        preamble = self.prompt_text.get("1.0", "end").strip()
        prompt = engine_question(random.randrange(QUESTION_COUNT))
        if preamble:
            prompt = f"{preamble}\n\n{prompt}"
        self.busy = True
        self.status_label.config(text=f"Sending via {self.backend_name}...")
        size = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        threading.Thread(target=self._worker, args=(self.backend_name, prompt, size, self.run_cancel),
                         daemon=True).start()

    def _run_on_ui(self, fn):
        """Run fn on the Tk thread and wait for it. Called from worker threads."""
        done = threading.Event()
        self.ui_calls.put((fn, done))
        done.wait(15)

    def _hide_for_capture(self):
        self._was_fullscreen = bool(self.root.attributes("-fullscreen"))
        self.root.withdraw()

    def _show_after_capture(self):
        self.root.deiconify()
        self.root.attributes("-fullscreen", self._was_fullscreen)
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    def _worker(self, backend_name: str, prompt: str, size: tuple[int, int], cancel: threading.Event):
        """Send one prompt. Results carry the run's cancel event so stale results from a stopped run are ignored."""
        try:
            backend = self._build_backend()
            say = lambda text: self.results.put(("status", text, cancel))
            if isinstance(backend, WindowBackend):
                hooks = (lambda: self._run_on_ui(self._hide_for_capture),
                         lambda: self._run_on_ui(self._show_after_capture))
                reply = backend.send(prompt, hooks=hooks, image_dir=self.data_dir / "chatgpt-images",
                                     cancel=cancel, status=say)
            elif isinstance(backend, TabBackend):
                reply = backend.send(prompt, image_dir=self.data_dir / "chatgpt-images",
                                     cancel=cancel, status=say)
            else:
                say(f"Sending via {backend_name}...")
                reply = backend.send(prompt)
            if isinstance(reply, str):
                reply = Reply(text=reply)
            if reply and (reply.text or reply.images):
                self.results.put(("reply", self._render_items(reply, size), cancel))
            else:
                self.results.put(("ok", f"Sent via {backend_name}.", cancel))
        except SendCancelled:
            self.results.put(("cancelled", "", cancel))
        except Exception as exc:
            self.results.put(("error", f"{backend_name} error: {exc}", cancel))

    def _load_slides(self):
        self.slides = render_slides(self.data_dir)

    def _save_cards(self, cards: list) -> list[Path]:
        out_dir = self.data_dir / "replies"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for card in cards:
            path = out_dir / f"reply-{time.time_ns()}.png"
            card.save(path)
            paths.append(path)
        return paths

    def _render_items(self, reply: Reply, size: tuple[int, int]) -> list[Path]:
        """Render the reply as cards. Each image card carries the next piece of the reply's text."""
        width, height = size
        chunks = split_reply(reply.text)
        cards = []
        for n, picture in enumerate(reply.images, 1):
            body = chunks.pop(0) if chunks else ""
            cards.append(render_text_card(f"image {n}", body, width, height, images=[picture]))
        start = len(reply.images) + 1
        cards += [render_text_card(str(n), chunk, width, height)
                  for n, chunk in enumerate(chunks, start)]
        return self._save_cards(cards)

    def _clear_items(self):
        while True:
            try:
                self.display_queue.get_nowait()
            except queue.Empty:
                return

    def _advance_items(self):
        """Show the next queued card for ITEM_SECONDS. Runs on the Tk thread."""
        now = time.monotonic()
        if self.showing_reply and now < self.phase_until:
            return
        try:
            path = self.display_queue.get_nowait()
        except queue.Empty:
            if self.showing_reply:
                self.showing_reply = False
                self.slide_label.place_forget()
            if self.waiting_for_slides:
                # The reply's last slide has finished, so the next question can go out.
                self.waiting_for_slides = False
                self._continue_loop(NEXT_SEND_MS)
            return
        image = Image.open(path).convert("RGB")
        if image.size != (self.root.winfo_width(), self.root.winfo_height()):
            image = image.resize((max(1, self.root.winfo_width()), max(1, self.root.winfo_height())))
        self._reply_photo = ImageTk.PhotoImage(image)
        self.slide_label.config(image=self._reply_photo)
        self.slide_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.slide_label.lift()
        self.showing_slide = False
        self.showing_reply = True
        self.phase_until = now + ITEM_SECONDS

    def _update_slides(self):
        now = time.monotonic()
        if self.showing_reply or now < self.phase_until or not self.slides:
            return
        if self.showing_slide:
            self.slide_label.place_forget()
            self.showing_slide = False
            self.phase_until = now + OVERLAY_SECONDS
            return
        self.slide_index = (self.slide_index + 1) % len(self.slides)
        image = Image.open(self.slides[self.slide_index]).convert("RGB")
        image = image.resize((self.root.winfo_width(), self.root.winfo_height()))
        self._slide_photo = ImageTk.PhotoImage(image)
        self.slide_label.config(image=self._slide_photo)
        self.slide_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.slide_label.lift()
        self.showing_slide = True
        self.phase_until = now + SLIDE_SECONDS

    def _tick(self):
        try:
            self._step()
        except Exception:
            with (self.data_dir / "overlay-errors.log").open("a", encoding="utf-8") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}\n")
        self.root.after(FRAME_MS, self._tick)

    def _step(self):
        self.path.width = self.root.winfo_width()
        if not self.chrome_hidden:
            self.arrow.place(x=int(self.path.step()), y=self.root.winfo_height() - 24)
        self._advance_items()
        self._update_slides()
        self.status_label.lift()
        try:
            while True:
                fn, done = self.ui_calls.get_nowait()
                try:
                    fn()
                finally:
                    done.set()
        except queue.Empty:
            pass
        try:
            while True:
                status, payload, token = self.results.get_nowait()
                if status == "status":
                    if token is self.run_cancel:
                        self.status_label.config(text=payload)
                    continue
                self.busy = False
                if token is not None and token is not self.run_cancel:
                    continue
                if status == "cancelled":
                    continue
                if status == "reply":
                    for path in payload:
                        self.display_queue.put(path)
                    self.waiting_for_slides = True
                    self.status_label.config(text=f"Showing {len(payload)} items from ChatGPT. Next question after the last slide.")
                    continue
                self.status_label.config(text=payload)
                self._continue_loop(interval_seconds(self.interval_minutes) * 1000)
        except queue.Empty:
            pass
        try:
            self.root.config(cursor="none" if (not self.revealed and self.idle.should_hide_cursor()) else "")
        except tk.TclError:
            pass

    def toggle_fullscreen(self):
        self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))
        if not self.running:
            self.status_label.config(text="Fullscreen" if self.root.attributes("-fullscreen") else "Windowed (Esc or F11 to go fullscreen)")

    def quit(self):
        self._stop()
        self.root.destroy()

    def run(self):
        self.root.after(200, self.root.focus_force)
        if self.backend_name in ("window", "tab"):
            self.root.after(1500, self._start)
        self.root.mainloop()


def run_overlay(data_dir: Path, backend: str = "api", interval_minutes: int = 3):
    Overlay(data_dir, backend=backend, interval_minutes=interval_minutes).run()
