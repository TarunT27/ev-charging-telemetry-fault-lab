"""Immutable domain models for deterministic telemetry simulations."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields, replace
from enum import Enum, StrEnum
from typing import Any


class FaultType(StrEnum):
    """Fault modes supported by the lab."""

    TIMEOUT = "timeout"
    DELAY = "delay"
    CORRUPT = "corrupt"
    SPIKE = "spike"
    STUCK = "stuck"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out-of-order"
    CONNECTION_DROP = "connection-drop"
    INCOMPLETE_MESSAGE = "incomplete-message"


class ChargerState(StrEnum):
    CONNECTED = "connected"
    CHARGING = "charging"
    OFFLINE = "offline"
    RECONNECTING = "reconnecting"
    RECOVERED = "recovered"


@dataclass(frozen=True, slots=True)
class FaultProfile:
    fault_type: FaultType
    rate: float = 0.1
    severity: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.rate) or not 0.0 <= self.rate <= 1.0:
            raise ValueError("fault rate must be between 0 and 1")
        if not math.isfinite(self.severity) or not 0.1 <= self.severity <= 10.0:
            raise ValueError("fault severity must be between 0.1 and 10")


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    name: str
    seed: int = 27
    charger_count: int = 1
    samples_per_charger: int = 60
    interval_ms: int = 1_000
    start_timestamp_ms: int = 1_735_689_600_000
    fault_profiles: tuple[FaultProfile, ...] = ()

    def __post_init__(self) -> None:
        clean_name = self.name.strip()
        if not clean_name or len(clean_name) > 80:
            raise ValueError("scenario name must contain 1 to 80 characters")
        if not 1 <= self.charger_count <= 20:
            raise ValueError("charger_count must be between 1 and 20")
        if not 5 <= self.samples_per_charger <= 1_000:
            raise ValueError("samples_per_charger must be between 5 and 1000")
        if not 100 <= self.interval_ms <= 60_000:
            raise ValueError("interval_ms must be between 100 and 60000")
        if self.start_timestamp_ms < 0:
            raise ValueError("start_timestamp_ms cannot be negative")
        if sum(profile.rate for profile in self.fault_profiles) > 1.0:
            raise ValueError("combined fault rates cannot exceed 1")
        object.__setattr__(self, "name", clean_name)


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    charger_id: str
    session_id: str
    sequence: int
    timestamp_ms: int
    power_kw: float
    voltage_v: float
    current_a: float
    temperature_c: float
    soc_percent: float
    charging_state: ChargerState = ChargerState.CHARGING
    connection_ok: bool = True
    diagnostic_code: str = "OK"

    def __post_init__(self) -> None:
        if not self.charger_id.strip() or len(self.charger_id) > 64:
            raise ValueError("charger_id must contain 1 to 64 characters")
        if not self.session_id.strip() or len(self.session_id) > 64:
            raise ValueError("session_id must contain 1 to 64 characters")
        if self.sequence < 0 or self.timestamp_ms < 0:
            raise ValueError("sequence and timestamp must be non-negative")
        measurements = (
            self.power_kw,
            self.voltage_v,
            self.current_a,
            self.temperature_c,
            self.soc_percent,
        )
        if not all(math.isfinite(value) for value in measurements):
            raise ValueError("telemetry measurements must be finite")

    def with_changes(self, **changes: Any) -> TelemetrySample:
        """Return a changed copy; source telemetry is never mutated."""

        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class FaultEvent:
    charger_id: str
    sequence: int
    fault_type: FaultType
    detail: str
    dropped: bool = False


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    charger_id: str
    sequence: int
    timestamp_ms: int
    rule: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class ScenarioMetrics:
    total_input: int
    total_output: int
    accepted: int
    rejected: int
    dropped: int
    injected_faults: int
    detected_faults: int
    detection_rate: float
    average_power_kw: float
    energy_kwh: float
    p95_delay_ms: int
    recovered_faults: int
    recovery_rate: float
    retry_count: int
    reconnect_count: int
    unsafe_actions: int


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    charger_id: str
    sequence: int
    action: str
    outcome: str
    detail: str


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    findings: tuple[DiagnosticFinding, ...]
    metrics: ScenarioMetrics


def _to_primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {field.name: _to_primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_to_primitive(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_primitive(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    config: ScenarioConfig
    original_samples: tuple[TelemetrySample, ...]
    observed_samples: tuple[TelemetrySample, ...]
    controller_samples: tuple[TelemetrySample, ...]
    events: tuple[FaultEvent, ...]
    recovery_actions: tuple[RecoveryAction, ...]
    report: DiagnosticReport

    def to_dict(self, *, include_samples: bool = True, max_records: int | None = None) -> dict[str, Any]:
        def limited(values: tuple[Any, ...]) -> tuple[Any, ...]:
            if max_records is None or len(values) <= max_records:
                return values
            stride = math.ceil(len(values) / max_records)
            return values[::stride][:max_records]

        payload = {
            "config": _to_primitive(self.config),
            "metrics": _to_primitive(self.report.metrics),
            "events": _to_primitive(limited(self.events)),
            "recovery_actions": _to_primitive(limited(self.recovery_actions)),
            "findings": _to_primitive(limited(self.report.findings)),
            "meta": {
                "total_events": len(self.events),
                "total_recovery_actions": len(self.recovery_actions),
                "total_findings": len(self.report.findings),
                "total_source_samples": len(self.original_samples),
                "total_observed_samples": len(self.observed_samples),
                "total_controller_samples": len(self.controller_samples),
            },
        }
        if include_samples:
            payload["samples"] = _to_primitive(limited(self.observed_samples))
            payload["controller_samples"] = _to_primitive(limited(self.controller_samples))
        return payload

    def to_json(self, *, indent: int = 2, include_samples: bool = True) -> str:
        return json.dumps(self.to_dict(include_samples=include_samples), indent=indent, sort_keys=True)
