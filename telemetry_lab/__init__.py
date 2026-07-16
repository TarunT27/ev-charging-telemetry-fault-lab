"""Deterministic EV charging telemetry fault injection and diagnostics."""

from telemetry_lab.models import ChargerState, FaultProfile, FaultType, ScenarioConfig, ScenarioResult, TelemetrySample
from telemetry_lab.service import run_scenario

__all__ = [
    "ChargerState",
    "FaultProfile",
    "FaultType",
    "ScenarioConfig",
    "ScenarioResult",
    "TelemetrySample",
    "run_scenario",
]
__version__ = "1.0.0"
