import argparse, signal, sys, time
from pathlib import Path
from .config import Settings
from .data.catalog import demo_catalog, load_csv
from .engine.cycle import run_cycle
from .scheduler.base import Scheduler
from .storage import Store

def main():
    p = argparse.ArgumentParser(prog="ushi", description="USHI Generative Snake developer prototype")
    sub = p.add_subparsers(dest="command", required=True)
    once = sub.add_parser("run-once", help="Run one complete USHI cycle")
    once.add_argument("--data", type=Path)
    dev = sub.add_parser("dev", help="Run continuous developer cycles until Ctrl+C")
    dev.add_argument("--interval", type=int, default=30)
    dev.add_argument("--power", choices=["minimum","balanced","performance"], default="minimum")
    status = sub.add_parser("status")
    export = sub.add_parser("export"); export.add_argument("--cycle", type=int, required=True)
    scr = sub.add_parser("screensaver", help="Fullscreen prompt overlay (api, web, desktop, or window backend)")
    scr.add_argument("--backend", choices=["api","web","desktop","window"], default="api")
    scr.add_argument("--interval", type=int, choices=[1,3], default=3)
    args = p.parse_args()
    if args.command == "screensaver":
        from .screensaver import run_overlay
        run_overlay(Settings().data_dir, backend=args.backend, interval_minutes=args.interval)
        return
    settings = Settings(power_mode=getattr(args, "power", "minimum"))
    store = Store(settings.database_path)
    if args.command == "status":
        for item in store.history(): print(f"Cycle {item['cycle']:04d} · {item['created_utc']} · {item['report']['leader']['candidate_id']}")
        store.close(); return
    if args.command == "export":
        path = settings.data_dir / "exports" / f"cycle-{args.cycle:04d}.json"
        print(path.read_text() if path.exists() else f"No export found: {path}")
        store.close(); return
    stars = load_csv(args.data) if getattr(args, "data", None) else demo_catalog()
    scheduler = Scheduler(settings.power_mode)
    running = True
    def stop(*_):
        nonlocal running
        running = False
        print("\nStop requested. Current cycle will finish; state is already checkpointed per cycle.")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while running:
            cycle = store.next_cycle()
            report = run_cycle(cycle, stars, store, scheduler, settings.data_dir, settings.power_mode)
            print(f"Cycle {cycle:04d} complete · leader {report['leader']['candidate_id']} · 21:9 SVG: {settings.data_dir / 'renders' / f'cycle-{cycle:04d}.svg'}")
            if args.command == "run-once": break
            for _ in range(max(1, args.interval)):
                if not running: break
                time.sleep(1)
    finally:
        store.close()

if __name__ == "__main__": main()
