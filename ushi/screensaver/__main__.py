import argparse
from pathlib import Path

from ushi.screensaver import run_overlay


def main():
    p = argparse.ArgumentParser(prog="Milkyway Mapper ScreenSaver", description="Milkyway Mapper fullscreen prompt overlay")
    p.add_argument("--backend", choices=["api", "web", "desktop"], default="api")
    p.add_argument("--interval", type=int, choices=[1, 3], default=3)
    p.add_argument("--data", type=Path, default=Path("ushi-data"))
    args = p.parse_args()
    run_overlay(args.data, backend=args.backend, interval_minutes=args.interval)


if __name__ == "__main__":
    main()
