from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("ushi-data")
    power_mode: str = "minimum"
    hbm_residency: str = "demand"
    hash_algorithm: str = "BLAKE3"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ushi.sqlite3"
