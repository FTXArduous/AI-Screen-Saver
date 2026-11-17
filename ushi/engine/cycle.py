import json
from pathlib import Path
from ..hashing import record_hashes
from ..models import CandidateResult, StarRecord
from .candidates import build_candidates
from ..render.dashboard import render_21_9

def run_cycle(cycle: int, stars: list[StarRecord], store, scheduler, data_dir: Path, power_mode: str) -> dict:
    candidates = build_candidates()
    ranked = sorted(candidates, key=lambda c: c.total_score, reverse=True)
    hashes = [record_hashes(s.canonical()) for s in stars]
    report = {
        "cycle": cycle,
        "operation": "USHI_GENERATIVE_SNAKE",
        "execution": "local_software_prototype",
        "input_count": len(stars),
        "input_sources": sorted(set(s.source for s in stars)),
        "candidate_count": len(candidates),
        "scoring_status": "heuristic_priors_not_measured_benchmarks",
        "leader": ranked[0].as_dict(),
        "top_four": [c.as_dict() for c in ranked[:4]],
        "record_hashes": hashes,
        "temporal_projection": "not_computed_no_validated_velocity_covariance_model",
        "scheduler": scheduler.checkpoint_and_hop({"cycle": cycle, "leader": ranked[0].candidate_id}),
        "telemetry": scheduler.telemetry(),
        "power_mode": power_mode,
    }
    store.save_cycle(cycle, report, candidates)
    export_dir = data_dir / "exports"; export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / f"cycle-{cycle:04d}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    render_21_9(cycle, candidates, len(stars), data_dir / "renders" / f"cycle-{cycle:04d}.svg", power_mode, scheduler.telemetry())
    return report
