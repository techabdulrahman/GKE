from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Finding:
    source: str            # gke | github | grafana
    kind: str              # e.g. ImagePullBackOff, WorkflowFailed, AlertFiring
    severity: str          # info | warning | critical
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Action:
    action: str            # rollout_undo | rollout_restart | none
    target: str            # deployment name
    reason: str
    auto: bool = True      # False = advice only, never executed

    def to_dict(self):
        return asdict(self)


@dataclass
class Diagnosis:
    root_cause: str
    confidence: str        # low | medium | high
    correlation: str       # how GKE / GitHub / Grafana evidence ties together
    actions: list[Action]
    engine: str            # gemini | rules

    def to_dict(self):
        return asdict(self)
