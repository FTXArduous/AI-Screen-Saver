import json, sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .models import CandidateResult

class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS cycles (cycle INTEGER PRIMARY KEY, created_utc TEXT, status TEXT, report_json TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS candidates (cycle INTEGER, candidate_id TEXT, result_json TEXT, PRIMARY KEY(cycle,candidate_id))")
        self.db.commit()

    def next_cycle(self) -> int:
        row = self.db.execute("SELECT COALESCE(MAX(cycle),0)+1 FROM cycles").fetchone()
        return int(row[0])

    def save_cycle(self, cycle: int, report: dict, candidates: list[CandidateResult]):
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("INSERT OR REPLACE INTO cycles VALUES (?,?,?,?)", (cycle, now, "completed", json.dumps(report, sort_keys=True)))
        self.db.executemany("INSERT OR REPLACE INTO candidates VALUES (?,?,?)", [(cycle,c.candidate_id,json.dumps(c.as_dict(),sort_keys=True)) for c in candidates])
        self.db.commit()

    def history(self, limit: int = 20):
        rows = self.db.execute("SELECT cycle,created_utc,report_json FROM cycles ORDER BY cycle DESC LIMIT ?", (limit,)).fetchall()
        return [{"cycle": r[0], "created_utc": r[1], "report": json.loads(r[2])} for r in rows]

    def close(self): self.db.close()
