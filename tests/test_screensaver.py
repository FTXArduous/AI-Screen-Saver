import numpy as np
import pytest
from PIL import Image

from ushi.screensaver.background import MAX_FRAMES, PLAYBACK_FPS, BackgroundLoop, Trajectory, trace
from ushi.screensaver import backends
from ushi.screensaver.backends import _clear_browser_cache, _find_reply_key, _reply_text, extract_text
from ushi.screensaver.engine import ArrowPath, IdleTracker, interval_seconds
from ushi.screensaver.questions import BASES, QUESTION_COUNT, TARGETS, engine_question


class _FakePage:
    def __init__(self, result):
        self.result = result

    def evaluate(self, script, arg=None):
        return self.result


def test_stale_reply_is_not_read_again_when_question_is_missing():
    stale = {"question": False, "reply": "old-key", "text": "ChatGPT said: 42"}
    assert _find_reply_key(_FakePage(stale), "How far is Sirius?", set(), previous="ChatGPT said: 42") == (False, None)
    fresh = {"question": False, "reply": "new-key", "text": "ChatGPT said: 57"}
    assert _find_reply_key(_FakePage(fresh), "How far is Sirius?", set(), previous="ChatGPT said: 42") == (False, "new-key")


def test_clear_browser_cache_keeps_login_data(tmp_path):
    (tmp_path / "Default" / "Cache").mkdir(parents=True)
    (tmp_path / "Default" / "Cache" / "entry").write_text("stale")
    (tmp_path / "Default" / "Service Worker").mkdir()
    (tmp_path / "Default" / "Cookies").write_text("session")
    _clear_browser_cache(tmp_path)
    assert not (tmp_path / "Default" / "Cache").exists()
    assert not (tmp_path / "Default" / "Service Worker").exists()
    assert (tmp_path / "Default" / "Cookies").read_text() == "session"
    assert len(TARGETS) == len(BASES) == QUESTION_COUNT == 16
    assert len(set(BASES)) == 16
    assert TARGETS[0].name in engine_question(0)
    assert f"base {BASES[5]}" in engine_question(5)
    assert engine_question(QUESTION_COUNT) == engine_question(0)


def test_interval_only_allows_one_or_three_minutes():
    assert interval_seconds(1) == 60
    assert interval_seconds(3) == 180
    with pytest.raises(ValueError):
        interval_seconds(2)


def test_arrow_bounces_within_bottom_edge():
    path = ArrowPath(width=100, size=20, speed=30)
    positions = [path.step() for _ in range(10)]
    assert all(0 <= x <= 80 for x in positions)
    assert 80 in positions and 0 in positions


def test_arrow_freeze_holds_position_until_unpaused():
    path = ArrowPath(width=100, size=20, speed=5)
    path.step()
    frozen = path.x
    path.paused = True
    assert [path.step() for _ in range(5)] == [frozen] * 5
    path.paused = False
    assert path.step() != frozen


def test_cursor_hides_only_after_idle_timeout():
    now = [0.0]
    idle = IdleTracker(timeout=7.0, clock=lambda: now[0])
    now[0] = 6.9
    assert not idle.should_hide_cursor()
    now[0] = 7.0
    assert idle.should_hide_cursor()
    idle.activity()
    assert not idle.should_hide_cursor()


def test_extract_text_reads_responses_output_items():
    data = {"output": [{"content": [{"type": "output_text", "text": "Hello "}, {"type": "output_text", "text": "world"}]}]}
    assert extract_text(data) == "Hello world"
    assert extract_text({"output_text": "direct"}) == "direct"


class _FakeMessage:
    def __init__(self, text):
        self.text = text

    def inner_text(self):
        return self.text


def test_reply_text_drops_hidden_chatgpt_said_label():
    assert _reply_text(_FakeMessage("ChatGPT said:\nMilky Way map\n4.2 ly")) == "Milky Way map\n4.2 ly"
    assert _reply_text(_FakeMessage("Plain reply")) == "Plain reply"


def test_reply_card_keeps_screen_size_for_long_reply():
    from ushi.screensaver.slides import render_text_card

    card = render_text_card("Question", "0123456789." * 2000, 640, 360)
    assert card.size == (640, 360)


def test_split_reply_keeps_chunks_under_limit_and_all_words():
    from ushi.screensaver.slides import split_reply

    text = "alpha beta gamma " * 60 + "\n\n" + "x" * 500
    chunks = split_reply(text, limit=200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert "".join("".join(chunks).split()) == "".join(text.split())


def test_reply_card_places_captured_image_above_text(tmp_path):
    from PIL import Image

    from ushi.screensaver.slides import render_text_card

    picture = tmp_path / "picture.png"
    Image.new("RGB", (1600, 400), "red").save(picture)
    card = render_text_card("Question", "Answer text", 800, 450, images=[picture])
    assert card.size == (800, 450)
    # The top of the card holds the red image, so the image was pasted and not skipped.
    assert card.getpixel((400, 40)) == (255, 0, 0)


def test_background_keeps_only_newest_frames_on_disk(tmp_path):
    loop = BackgroundLoop(tmp_path / "background")
    loop.folder.mkdir()
    paths = [loop.add(Image.new("RGB", (4, 4))) for _ in range(MAX_FRAMES + 5)]
    assert sorted(loop.folder.glob("bg-*.jpg")) == sorted(paths[-MAX_FRAMES:])


def test_background_plays_each_frame_once_in_order(tmp_path):
    loop = BackgroundLoop(tmp_path / "background")
    loop.folder.mkdir()
    paths = [loop.add(Image.new("RGB", (4, 4))) for _ in range(3)]
    assert [loop.take_next() for _ in range(4)] == paths + [None]


def test_consecutive_background_frames_change_only_slightly():
    trajectory = Trajectory(np.random.default_rng(7))
    trajectory.advance(1.0 / PLAYBACK_FPS)
    first = np.asarray(trace(trajectory.scene()), dtype=float)
    trajectory.advance(1.0 / PLAYBACK_FPS)
    second = np.asarray(trace(trajectory.scene()), dtype=float)
    assert first.shape == second.shape == (108, 192, 3)
    assert 0 < np.abs(first - second).mean() < 8


def test_app_does_not_relaunch_when_app_is_open_without_port(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(backends, "_cdp_running", lambda url=None: False)
    monkeypatch.setattr(backends, "_find_app_exe", lambda: "ChatGPT.exe")
    monkeypatch.setattr(backends, "_app_process_running", lambda: True)
    monkeypatch.setattr(backends.subprocess, "Popen", lambda *a, **k: launched.append(a))
    with pytest.raises(RuntimeError, match="already open without"):
        backends.AppBackend(tmp_path)._ensure_browser()
    assert launched == []
