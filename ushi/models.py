from dataclasses import asdict, dataclass
from typing import Any

@dataclass(frozen=True)
class StarRecord:
    oid: str
    x_ly: float
    y_ly: float
    z_ly: float
    vx_kms: float = 0.0
    vy_kms: float = 0.0
    vz_kms: float = 0.0
    epoch_year: float = 2026.0
    frame: str = "UNSPECIFIED_CARTESIAN"
    source: str = "user_csv"

    def canonical(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class CandidateResult:
    candidate_id: str
    radix: int
    subdivision: str
    integer_digits: int
    fractional_digits: int
    compactness: float
    uniformity: float
    navigation: float
    compute_efficiency: float
    astronomy_suitability: float
    total_score: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
