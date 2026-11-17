import ctypes
import os
import queue
import random
import threading
import time
import tkinter as tk
import traceback
from collections import deque
from pathlib import Path

from PIL import Image, ImageTk

from .background import BackgroundLoop, PLAYBACK_FPS
from .backends import AppBackend, BROWSER_NAMES, Reply, SendCancelled, TabBackend
from .engine import ArrowPath, IdleTracker, interval_seconds, ALLOWED_INTERVAL_MINUTES
from .questions import QUESTION_COUNT, engine_question
from .slides import render_slides, render_text_card, split_reply

FRAME_MS = 16
SLIDE_SECONDS = 2
OVERLAY_SECONDS = 2
ITEM_SECONDS = 4.8
NEXT_SEND_MS = 2000
STATUS_SPEED = 45.0
BACKEND_NAMES = ("tab", "app")
ESC_TRIPLE_SECONDS = 1.5
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _keep_system_awake(awake: bool) -> None:
    """Keep Windows from sleeping or entering power saving while the screensaver runs."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if awake else 0))


class Overlay:
    def __init__(self, data_dir: Path, backend: str = "tab", interval_minutes: int = 3):
        self.data_dir = data_dir
        self.backend_name = backend
        self.browser = "edge"
        self.interval_minutes = interval_minutes
        self.running = False
        self.chrome_hidden = False
        self.revealed = False

        self.results: queue.Queue = queue.Queue()
        self.display_queue: queue.Queue = queue.Queue()
        self.run_cancel = threading.Event()
        self.busy = False
        self.idle = IdleTracker()
        self._timer = None
        self._escape_times: deque = deque(maxlen=3)
        self.slides: list[Path] = []
        self.slide_index = -1
        self.showing_slide = False
        self.showing_reply = False
        self.waiting_for_slides = False
        self.phase_until = time.monotonic() + OVERLAY_SECONDS
        self._overlay_rgb = None
        self._overlay_mask = None
        self._overlay_photo = None
        self._bg_image = None
        self._bg_photo = None
        self._bg_next = 0.0
        self.background = BackgroundLoop(self.data_dir / "background")
        self.background.start()
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

        self.bg_label = tk.Label(self.root, bg="black", bd=0)
        self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)

        self.arrow = tk.Label(self.root, text="\u25bc", bg="#222222", fg="white",
                              font=("Segoe UI", 8), cursor="hand2")
        self.arrow.bind("<Button-1>", lambda _e: self._show_menu())

        self.editor = tk.Frame(self.root, bg="black")
        self.prompt_text = tk.Text(self.editor, height=4, width=70, bg="#111111", fg="white",
                                   insertbackground="white", wrap="word")
        self.prompt_text.pack()

        self.status_label = tk.Label(self.root, text="", bg="black", fg="#aaaaaa", wraplength=1200,
                                     justify="center", font=("Segoe UI", 11))
        self.status_label.place(x=100, y=100)
        self._status_pos = [100.0, 100.0]
        self._status_vel = [STATUS_SPEED, STATUS_SPEED]
        self._status_last = time.monotonic()

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
        self.menu.add_cascade(label="Browser", menu=browser_menu)
        interval_menu = tk.Menu(self.menu, tearoff=0)
        for minutes in ALLOWED_INTERVAL_MINUTES:
            interval_menu.add_command(label=f"{minutes} min", command=lambda m=minutes: self.set_interval(m))
        self.menu.add_cascade(label="Interval", menu=interval_menu)
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
        self.status_label.config(text=f"Browser: {name}")

    def _on_key_one(self, event):
        if event.widget is self.prompt_text:
            return
        self.toggle_running()

    def set_interval(self, minutes: int):
        self.interval_minutes = minutes

    def _on_escape(self):
        now = time.monotonic()
        self._escape_times.append(now)
        if len(self._escape_times) == 3 and now - self._escape_times[0] <= ESC_TRIPLE_SECONDS:
            # Third quick Esc freezes or unfreezes the drop-down arrow and leaves fullscreen as it was.
            self._escape_times.clear()
            self.path.paused = not self.path.paused
            return
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
        _keep_system_awake(True)
        self._place_chrome()
        self._continue_loop(0)

    def _stop(self):
        self.running = False
        self.run_cancel.set()
        self.revealed = False
        _keep_system_awake(False)
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
        if self.backend_name == "app":
            return AppBackend(self.data_dir / "tab-profile")
        return TabBackend(self.data_dir / "tab-profile", browser=self.browser)

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

    def _worker(self, backend_name: str, prompt: str, size: tuple[int, int], cancel: threading.Event):
        """Send one prompt. Results carry the run's cancel event so stale results from a stopped run are ignored."""
        try:
            backend = self._build_backend()
            reply = backend.send(prompt, image_dir=self.data_dir / "chatgpt-images",
                                 cancel=cancel, status=lambda text: self.results.put(("status", text, cancel)),
                                 partial=lambda piece: self.results.put(
                                     ("partial", self._render_items(piece, size), cancel)))
            # Always report the reply, even if everything was already streamed, so the next question waits for the slides.
            self.results.put(("reply", self._render_items(reply, size), cancel))
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
        self._show_overlay(Image.open(path).convert("RGB"))
        self.showing_slide = False
        self.showing_reply = True
        self.phase_until = now + ITEM_SECONDS

    def _show_overlay(self, image: Image.Image):
        """Show a slide or card in front of the background. Dark pixels stay transparent so the background shows."""
        size = (max(1, self.root.winfo_width()), max(1, self.root.winfo_height()))
        self._overlay_rgb = image.resize(size)
        self._overlay_mask = self._overlay_rgb.convert("L")
        self._refresh_overlay()
        self.slide_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.slide_label.lift()

    def _refresh_overlay(self):
        base = self._bg_image
        if base is None or base.size != self._overlay_rgb.size:
            base = Image.new("RGB", self._overlay_rgb.size, "black")
        self._overlay_photo = ImageTk.PhotoImage(Image.composite(self._overlay_rgb, base, self._overlay_mask))
        self.slide_label.config(image=self._overlay_photo)

    def _update_background(self):
        """Show the next rendered frame in order at PLAYBACK_FPS, holding the last frame if rendering is behind."""
        now = time.monotonic()
        if now < self._bg_next:
            return
        path = self.background.take_next()
        if path is None:
            return
        self._bg_next = now + 1.0 / PLAYBACK_FPS
        try:
            size = (max(1, self.root.winfo_width()), max(1, self.root.winfo_height()))
            self._bg_image = Image.open(path).convert("RGB").resize(size, Image.Resampling.BILINEAR)
        except OSError:
            return
        self._bg_photo = ImageTk.PhotoImage(self._bg_image)
        self.bg_label.config(image=self._bg_photo)
        if self.showing_slide or self.showing_reply:
            self._refresh_overlay()

    def _bounce_status(self):
        """Move the status text slowly, bouncing diagonally off the screen edges like a DVD logo."""
        now = time.monotonic()
        dt = min(0.1, now - self._status_last)
        self._status_last = now
        max_x = max(0, self.root.winfo_width() - self.status_label.winfo_reqwidth())
        max_y = max(0, self.root.winfo_height() - self.status_label.winfo_reqheight())
        x, y = self._status_pos
        vx, vy = self._status_vel
        x += vx * dt
        y += vy * dt
        if x <= 0:
            x, vx = 0.0, abs(vx)
        elif x >= max_x:
            x, vx = float(max_x), -abs(vx)
        if y <= 0:
            y, vy = 0.0, abs(vy)
        elif y >= max_y:
            y, vy = float(max_y), -abs(vy)
        self._status_pos = [x, y]
        self._status_vel = [vx, vy]
        self.status_label.place(x=int(x), y=int(y))

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
        self._show_overlay(Image.open(self.slides[self.slide_index]).convert("RGB"))
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
        self._drain_results()
        self._advance_items()
        self._update_slides()
        self._update_background()
        self._bounce_status()
        self.status_label.lift()
        try:
            self.root.config(cursor="none" if (not self.revealed and self.idle.should_hide_cursor()) else "")
        except tk.TclError:
            pass

    def _drain_results(self):
        """Apply worker results on the Tk thread. Results from a stopped run are ignored by token."""
        try:
            while True:
                status, payload, token = self.results.get_nowait()
                if status == "status":
                    if token is self.run_cancel:
                        self.status_label.config(text=payload)
                    continue
                if status == "partial":
                    # Streamed cards show right away; the send is still running, so the loop stays busy.
                    if token is self.run_cancel:
                        for path in payload:
                            self.display_queue.put(path)
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
                    self.status_label.config(text=(f"Showing {len(payload)} items from ChatGPT. Next question after the last slide."
                                                   if payload else "ChatGPT returned nothing to show. Next question after a short wait."))
                    continue
                self.status_label.config(text=payload)
                self._continue_loop(interval_seconds(self.interval_minutes) * 1000)
        except queue.Empty:
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
        self.root.mainloop()


def run_overlay(data_dir: Path, backend: str = "tab", interval_minutes: int = 3):
    Overlay(data_dir, backend=backend, interval_minutes=interval_minutes).run()
