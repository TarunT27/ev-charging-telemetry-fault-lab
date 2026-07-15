"""Immutable telemetry samples and repeatable fault scenarios."""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


class FaultType(str, Enum):
    TIMEOUT = "timeout"
    DELAY = "delay"
    CORRUPT = "corrupt"


@dataclass(frozen=True)
class TelemetrySample:
    charger_id: str
    power_kw: float
    timestamp_ms: int


def apply_fault(
    sample: TelemetrySample,
    fault: FaultType,
    delay_ms: int = 1000,
) -> TelemetrySample | None:
    if fault is FaultType.TIMEOUT:
        return None
    if fault is FaultType.DELAY:
        return replace(sample, timestamp_ms=sample.timestamp_ms + delay_ms)
    if fault is FaultType.CORRUPT:
        return replace(sample, power_kw=-1.0)
    raise ValueError(f"unsupported fault: {fault}")


def validate_sample(sample: TelemetrySample) -> bool:
    return bool(sample.charger_id) and sample.power_kw >= 0.0 and sample.timestamp_ms >= 0


def run_scenario(samples: Iterable[TelemetrySample], fault: FaultType) -> dict[str, int]:
    counters = {"accepted": 0, "rejected": 0, "dropped": 0}
    for sample in samples:
        changed = apply_fault(sample, fault)
        key = "dropped" if changed is None else "accepted" if validate_sample(changed) else "rejected"
        counters = {**counters, key: counters[key] + 1}
    return counters
