import pytest

from ushi.screensaver.backends import _reply_text, extract_text
from ushi.screensaver.engine import ArrowPath, IdleTracker, interval_seconds
from ushi.screensaver.questions import BASES, QUESTION_COUNT, TARGETS, engine_question


def test_engine_question_covers_sixteen_targets_in_distinct_bases():
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
