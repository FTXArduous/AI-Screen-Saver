from dataclasses import dataclass

@dataclass
class ResourceStatus:
    backend: str = "simulation"
    gpu_connected: bool = False
    hbm_connected: bool = False
    cluster_connected: bool = False
    power_mode: str = "minimum"

class Scheduler:
    """Safe placeholder. Real cluster migration must be implemented for an authorized scheduler."""
    def __init__(self, power_mode: str = "minimum"):
        self.status = ResourceStatus(power_mode=power_mode)

    def checkpoint_and_hop(self, checkpoint: dict) -> dict:
        return {"performed": False, "reason": "No authorized cluster backend configured", "checkpointed": True}

    def telemetry(self) -> dict:
        return {"backend": self.status.backend, "gpu": "not_connected", "hbm": "not_connected", "cluster": "not_connected"}
