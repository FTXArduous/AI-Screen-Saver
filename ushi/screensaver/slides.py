import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
FONT_NAMES = ("consola.ttf", "cour.ttf")


def find_edge() -> str | None:
    for path in EDGE_PATHS:
        if Path(path).exists():
            return path
    return shutil.which("msedge")


def svg_to_png(svg: Path, png: Path, width: int = 2100, height: int = 900) -> bool:
    if png.exists() and png.stat().st_mtime >= svg.stat().st_mtime:
        return True
    edge = find_edge()
    if edge is None:
        return False
    subprocess.run(
        [edge, "--headless", "--disable-gpu", f"--screenshot={png.resolve()}",
         f"--window-size={width},{height}", svg.resolve().as_uri()],
        capture_output=True, timeout=60, check=False,
    )
    return png.exists()


def render_slides(data_dir: Path) -> list[Path]:
    slides = []
    for svg in sorted((data_dir / "renders").glob("cycle-*.svg")):
        png = svg.with_suffix(".png")
        if svg_to_png(svg, png):
            slides.append(png)
    return slides


def _load_font(size: int):
    for name in FONT_NAMES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else f"{line} {word}"
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            # A word wider than the card (for example a long decimal) is broken by character.
            for char in word:
                if line and draw.textlength(line + char, font=font) > max_width:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return lines


def split_reply(text: str, limit: int = 450) -> list[str]:
    """Split a reply into chunks of at most `limit` characters, keeping paragraphs together when possible."""
    chunks: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        for piece in textwrap.wrap(paragraph, limit, break_long_words=True, break_on_hyphens=False):
            if current and len(current) + 2 + len(piece) > limit:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _fit_images(paths: list[Path], max_width: int, max_height: int) -> list[Image.Image]:
    per_image = max(1, max_height // len(paths))
    fitted = []
    for path in paths:
        picture = Image.open(path).convert("RGB")
        scale = min(max_width / picture.width, per_image / picture.height, 1.0)
        fitted.append(picture.resize((max(1, int(picture.width * scale)), max(1, int(picture.height * scale)))))
    return fitted


def render_text_card(title: str, body: str, width: int, height: int, images: list[Path] = ()) -> Image.Image:
    """Render the question, any captured images, and the reply as a full-screen black card.

    Images are stacked at the top using at most 60% of the height; the text shrinks to fit the rest.
    """
    image = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(image)
    margin = max(24, width // 30)
    max_width = width - 2 * margin
    y = margin
    if images:
        for picture in _fit_images([Path(p) for p in images], max_width, int(height * 0.6)):
            image.paste(picture, ((width - picture.width) // 2, y))
            y += picture.height + margin // 2
    available = height - margin - y
    size = 48
    while True:
        font = _load_font(size)
        line_height = int(size * 1.35)
        title_lines = _wrap(draw, title, font, max_width)
        body_lines = _wrap(draw, body, font, max_width)
        needed = (len(title_lines) + len(body_lines) + 1) * line_height
        if needed <= available or size <= 12:
            break
        size -= 2
    for line in title_lines:
        draw.text((margin, y), line, font=font, fill="#9a9a9a")
        y += line_height
    y += line_height
    for line in body_lines:
        draw.text((margin, y), line, font=font, fill="white")
        y += line_height
    return image
