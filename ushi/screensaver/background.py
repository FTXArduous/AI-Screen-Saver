"""Ray-traced glass tesseract used as the screensaver background.

The tesseract drifts and bounces across the screen, its 4D shape and rotation change slowly, and the
amber light moves a little per frame, so each frame is close to the previous one. Frames are traced
with numpy at TRACE_SIZE, saved as small JPEGs, and handed to the overlay in order at PLAYBACK_FPS.
Only the newest MAX_FRAMES are kept on disk, and frames are never deleted before they have played.
"""
import itertools
import math
import threading
import time
import traceback
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

TRACE_SIZE = (192, 108)
PLAYBACK_FPS = 24
MAX_FRAMES = 48
PLAYBACK_MARGIN = 4
CAMERA = np.array([0.0, 0.0, -6.0])
OBJECT_DEPTH = 6.0
OBJECT_HALF = 0.3
X_LIMIT = 0.5 * TRACE_SIZE[0] / TRACE_SIZE[1] - OBJECT_HALF
Y_LIMIT = 0.5 - OBJECT_HALF
SCREEN_SPEED = 0.05
SPIN_RATE = 0.35
SHAPE_DRIFT = 0.12
LIGHT_FREQ = 0.03
AMBER = np.array([1.0, 0.62, 0.22])
GLASS = np.array([0.55, 0.85, 1.0])
JOINT_RADIUS = 0.07
PLANES_4D = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))

_VERTS4 = np.array(list(itertools.product((-1.0, 1.0), repeat=4)))
_EDGES = [(i, j) for i in range(16) for j in range(i + 1, 16) if np.sum(_VERTS4[i] != _VERTS4[j]) == 1]
_PROJECTED0 = _VERTS4[:, :3] / (3.5 - _VERTS4[:, 3])[:, None]
_NORM0 = float(np.linalg.norm(_PROJECTED0, axis=1).max())


def _rotation(n: int, a: int, b: int, angle: float) -> np.ndarray:
    m = np.eye(n)
    c, s = math.cos(angle), math.sin(angle)
    m[a, a] = m[b, b] = c
    m[a, b], m[b, a] = -s, s
    return m


def _camera_rays(width: int, height: int) -> np.ndarray:
    tan_half = 0.5
    xs = ((np.arange(width) + 0.5) / width * 2 - 1) * tan_half * (width / height)
    ys = (1 - (np.arange(height) + 0.5) / height * 2) * tan_half
    x, y = np.meshgrid(xs, ys)
    dirs = np.stack([x, y, np.ones_like(x)], axis=-1).reshape(-1, 3)
    return dirs / np.linalg.norm(dirs, axis=1, keepdims=True)


def _intersect_cylinder(origin, dirs, a, b, radius, best) -> None:
    t_best, normal_best, kind_best = best
    axis = b - a
    length = float(np.linalg.norm(axis))
    k = axis / length
    oc = origin - a
    dv = dirs - (dirs @ k)[:, None] * k
    ov = oc - (oc @ k) * k
    qa = np.einsum("ij,ij->i", dv, dv)
    qb = 2.0 * (dv @ ov)
    qc = float(ov @ ov) - radius * radius
    disc = qb * qb - 4.0 * qa * qc
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (-qb - np.sqrt(np.maximum(disc, 0.0))) / (2.0 * qa)
    s = float(oc @ k) + t * (dirs @ k)
    valid = (disc >= 0) & (qa > 1e-9) & (t > 1e-4) & (s >= 0) & (s <= length)
    closer = valid & (t < t_best)
    if not closer.any():
        return
    tc = t[closer]
    rel = oc + tc[:, None] * dirs[closer] - s[closer, None] * k
    t_best[closer] = tc
    normal_best[closer] = rel / radius
    kind_best[closer] = 0


def _intersect_sphere(origin, dirs, center, radius, best) -> None:
    t_best, normal_best, kind_best = best
    oc = origin - center
    qb = 2.0 * (dirs @ oc)
    qc = float(oc @ oc) - radius * radius
    disc = qb * qb - 4.0 * qc
    with np.errstate(invalid="ignore"):
        t = (-qb - np.sqrt(np.maximum(disc, 0.0))) / 2.0
    closer = (disc >= 0) & (t > 1e-4) & (t < t_best)
    if not closer.any():
        return
    tc = t[closer]
    t_best[closer] = tc
    normal_best[closer] = (oc + tc[:, None] * dirs[closer]) / radius
    kind_best[closer] = 1


def _backdrop(dirs: np.ndarray, light: np.ndarray) -> np.ndarray:
    to_light = light - CAMERA
    to_light /= np.linalg.norm(to_light)
    facing = np.clip(dirs @ to_light, 0.0, 1.0)
    glow = facing ** 30 * 0.6 + facing ** 6 * 0.12
    base = np.array([0.03, 0.035, 0.05]) * (1.0 + 0.5 * dirs[:, 1:2])
    return base + AMBER * glow[:, None]


def _shade(dirs, t_best, normal_best, kind, light, intensity) -> np.ndarray:
    color = _backdrop(dirs, light)
    hit = np.isfinite(t_best)
    if not hit.any():
        return color
    d = dirs[hit]
    n = normal_best[hit]
    p = CAMERA + t_best[hit][:, None] * d
    v = -d
    to_light = light - p
    dist2 = np.einsum("ij,ij->i", to_light, to_light)[:, None]
    l = to_light / np.sqrt(dist2)
    h = l + v
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    ndv = np.clip(np.einsum("ij,ij->i", n, v), 0.0, 1.0)[:, None]
    ndl = np.clip(np.einsum("ij,ij->i", n, l), 0.0, 1.0)[:, None]
    ndh = np.clip(np.einsum("ij,ij->i", n, h), 0.0, 1.0)[:, None]
    atten = intensity / (1.0 + 0.1 * dist2)
    fresnel = 0.04 + 0.96 * (1.0 - ndv) ** 5
    spec = ndh ** 60 * atten
    glass = GLASS * (0.12 + 0.25 * (1.0 - fresnel)) + color[hit] * fresnel * 1.5 + AMBER * spec * 1.5
    glass += AMBER * ndl * atten * 0.12
    joint = AMBER * (0.35 + 0.9 * ndl * atten) + AMBER * spec * 0.8
    color[hit] = np.where((kind[hit] == 1)[:, None], joint, glass)
    return color


class Scene(NamedTuple):
    """World-space tesseract vertices and light for one frame."""

    points: np.ndarray
    light: np.ndarray
    intensity: float
    edge_radius: float


class Trajectory:
    """Advances the tesseract and light one frame at a time; the random start is the only big change."""

    def __init__(self, rng: np.random.Generator):
        self.t = 0.0
        self.angles = rng.uniform(0, 2 * math.pi, len(PLANES_4D))
        self.spin = rng.uniform(-SPIN_RATE, SPIN_RATE, len(PLANES_4D))
        self.radius = rng.uniform(1.2, 1.4)
        self.edge_radius = rng.uniform(0.03, 0.05)
        self.intensity = rng.uniform(1.2, 2.2)
        self.shape_freq = rng.uniform(0.03, 0.06, 4)
        self.shape_phase = rng.uniform(0, 2 * math.pi, 4)
        self.light_phase = rng.uniform(0, 2 * math.pi, 3)
        heading = rng.uniform(0, 2 * math.pi)
        self.velocity = SCREEN_SPEED * np.array([math.cos(heading), math.sin(heading)])
        self.screen = np.array([rng.uniform(-X_LIMIT, X_LIMIT), rng.uniform(-Y_LIMIT, Y_LIMIT)])

    def advance(self, dt: float) -> None:
        self.t += dt
        self.angles = self.angles + self.spin * dt
        self.screen = self.screen + self.velocity * dt
        for axis, limit in enumerate((X_LIMIT, Y_LIMIT)):
            if abs(self.screen[axis]) > limit:
                self.screen[axis] = math.copysign(limit, self.screen[axis])
                self.velocity[axis] = -self.velocity[axis]

    def scene(self) -> Scene:
        scale = 1 + SHAPE_DRIFT * np.sin(2 * math.pi * self.shape_freq * self.t + self.shape_phase)
        m4 = np.eye(4)
        for (a, b), angle in zip(PLANES_4D, self.angles):
            m4 = _rotation(4, a, b, angle) @ m4
        v4 = (_VERTS4 * scale) @ m4.T
        points = v4[:, :3] / (3.5 - v4[:, 3])[:, None] * (self.radius / _NORM0)
        center = CAMERA + np.array([self.screen[0], self.screen[1], 1.0]) * OBJECT_DEPTH
        wobble = np.sin(2 * math.pi * LIGHT_FREQ * self.t + self.light_phase)
        light = np.array([2.5 * wobble[0], 1.5 * wobble[1], -2.0 + 0.5 * wobble[2]])
        return Scene(points + center, light, self.intensity, self.edge_radius)


def trace(scene: Scene) -> Image.Image:
    """Ray-trace one frame of the tesseract at TRACE_SIZE."""
    width, height = TRACE_SIZE
    dirs = _camera_rays(width, height)
    t_best = np.full(len(dirs), np.inf)
    normal_best = np.zeros((len(dirs), 3))
    kind = np.zeros(len(dirs), dtype=np.int8)
    best = (t_best, normal_best, kind)
    for a, b in _EDGES:
        _intersect_cylinder(CAMERA, dirs, scene.points[a], scene.points[b], scene.edge_radius, best)
    for p in scene.points:
        _intersect_sphere(CAMERA, dirs, p, JOINT_RADIUS, best)
    color = _shade(dirs, t_best, normal_best, kind, scene.light, scene.intensity)
    color = 1.0 - np.exp(-1.4 * color)
    pixels = (np.clip(color, 0.0, 1.0) ** (1 / 2.2) * 255).astype(np.uint8).reshape(height, width, 3)
    return Image.fromarray(pixels)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


class BackgroundLoop:
    """Traces frames in order, keeps the newest MAX_FRAMES on disk, and hands them out once each."""

    def __init__(self, folder: Path):
        self.folder = folder
        self._frames: list[tuple[int, Path]] = []
        self._lock = threading.Lock()
        self._next_seq = 0
        self._played_seq = -1
        self._trajectory = Trajectory(np.random.default_rng())

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for old in self.folder.glob("bg-*.jpg"):
            _remove(old)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                with self._lock:
                    ahead = self._next_seq - 1 - self._played_seq
                if ahead >= MAX_FRAMES - PLAYBACK_MARGIN:
                    time.sleep(0.02)
                    continue
                self._trajectory.advance(1.0 / PLAYBACK_FPS)
                self.add(trace(self._trajectory.scene()))
            except Exception:
                with (self.folder.parent / "overlay-errors.log").open("a", encoding="utf-8") as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}\n")
                time.sleep(1.0)

    def add(self, frame: Image.Image) -> Path:
        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
        path = self.folder / f"bg-{seq:08d}.jpg"
        frame.save(path, quality=90)
        with self._lock:
            self._frames.append((seq, path))
            while len(self._frames) > MAX_FRAMES:
                _remove(self._frames.pop(0)[1])
        return path

    def take_next(self) -> Path | None:
        """Return the next frame that has not been played yet, or None if rendering has not caught up."""
        with self._lock:
            for seq, path in self._frames:
                if seq > self._played_seq:
                    self._played_seq = seq
                    return path
        return None
