import json
from blake3 import blake3

def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def digest(value: object) -> str:
    return blake3(canonical_json(value)).hexdigest()

def record_hashes(record: dict, projection: dict | None = None) -> dict[str, str]:
    oid = record["oid"]
    dmh = digest({"schema": "USHI-STAR-v1", "record": record})
    result = {"oid": oid, "dmh": dmh}
    if projection is not None:
        result["thi"] = digest({"schema": "USHI-PROJECTION-v1", "oid": oid, "projection": projection})
    return result
