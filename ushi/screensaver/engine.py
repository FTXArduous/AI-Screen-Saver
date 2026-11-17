from dataclasses import dataclass
import time
from typing import Callable

ALLOWED_INTERVAL_MINUTES = (1, 3)
CURSOR_HIDE_SECONDS = 7.0


def interval_seconds(minutes: int) -> int:
    if minutes not in ALLOWED_INTERVAL_MINUTES:
        raise ValueError(f"interval must be one of {ALLOWED_INTERVAL_MINUTES} minutes, got {minutes}")
    return minutes * 60


@dataclass
class ArrowPath:
    """Horizontal bounce of the drop-down arrow along the bottom edge."""
    width: int
    size: int = 20
    speed: float = 4.0
    x: float = 0.0
    direction: int = 1

    def step(self) -> float:
        max_x = max(0.0, float(self.width - self.size))
        self.x += self.direction * self.speed
        if self.x >= max_x:
            self.x, self.direction = max_x, -1
        elif self.x <= 0.0:
            self.x, self.direction = 0.0, 1
        return self.x


class IdleTracker:
    """Reports whether the cursor should be hidden after a period without movement."""

    def __init__(self, timeout: float = CURSOR_HIDE_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.timeout = timeout
        self._clock = clock
        self._last = clock()

    def activity(self) -> None:
        self._last = self._clock()

    def should_hide_cursor(self) -> bool:
        return self._clock() - self._last >= self.timeout
