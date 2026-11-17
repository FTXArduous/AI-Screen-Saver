import csv
from pathlib import Path
from ..models import StarRecord

def load_csv(path: Path) -> list[StarRecord]:
    records = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            records.append(StarRecord(
                oid=row["id"], x_ly=float(row["x_ly"]), y_ly=float(row["y_ly"]), z_ly=float(row["z_ly"]),
                vx_kms=float(row.get("vx_kms") or 0), vy_kms=float(row.get("vy_kms") or 0),
                vz_kms=float(row.get("vz_kms") or 0), epoch_year=float(row.get("epoch_year") or 2026),
                frame=row.get("frame") or "UNSPECIFIED_CARTESIAN", source=row.get("source") or "user_csv"))
    return records

def demo_catalog() -> list[StarRecord]:
    # Synthetic demonstration points only; deliberately not presented as measured stars.
    return [
        StarRecord("DEMO-001", 12.84, 0.751, 5.64, frame="DEMO_FRAME", source="synthetic_demo"),
        StarRecord("DEMO-002", 7.547, 20.418, -33.075, frame="DEMO_FRAME", source="synthetic_demo"),
        StarRecord("DEMO-003", -18.2, 11.4, 2.7, frame="DEMO_FRAME", source="synthetic_demo"),
        StarRecord("DEMO-004", 44.1, -8.2, 12.6, frame="DEMO_FRAME", source="synthetic_demo"),
    ]
