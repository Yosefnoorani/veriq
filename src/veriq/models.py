"""Result data model shared by all checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED = "SKIPPED"  # check not applicable (e.g. no reference given)


@dataclass
class CheckResult:
    name: str
    status: Status
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Report:
    target: str
    reference: str | None
    verdict: Status
    checks: list[CheckResult]
    metrics: dict[str, Any]
    circuit_text: str = ""
    reference_text: str = ""
    seconds: float = 0.0
    versions: dict[str, str] = field(default_factory=dict)
    # in-memory only (not serialized): the circuits that were checked, for certificates
    circuits: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "reference": self.reference,
            "verdict": self.verdict.value,
            "seconds": round(self.seconds, 3),
            "checks": [c.to_dict() for c in self.checks],
            "metrics": self.metrics,
            "versions": self.versions,
        }


def overall_verdict(checks: list[CheckResult]) -> Status:
    """FAIL if any check fails; PASS if every applicable check passes; else INCONCLUSIVE."""
    statuses = [c.status for c in checks if c.status != Status.SKIPPED]
    if any(s == Status.FAIL for s in statuses):
        return Status.FAIL
    if statuses and all(s == Status.PASS for s in statuses):
        return Status.PASS
    return Status.INCONCLUSIVE
