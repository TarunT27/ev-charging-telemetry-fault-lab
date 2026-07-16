"""Public facade for the fault-lab simulation engine."""

from telemetry_lab.diagnostics import analyze_telemetry
from telemetry_lab.faults import FaultApplication, FaultInjectionResult, apply_fault, inject_faults
from telemetry_lab.generator import generate_telemetry
from telemetry_lab.models import ChargerState, FaultProfile, FaultType, ScenarioConfig, ScenarioResult, TelemetrySample
from telemetry_lab.recovery import RecoveryResult, verify_recovery
from telemetry_lab.service import run_scenario

__all__ = [
    "ChargerState",
    "FaultApplication",
    "FaultInjectionResult",
    "FaultProfile",
    "FaultType",
    "RecoveryResult",
    "ScenarioConfig",
    "ScenarioResult",
    "TelemetrySample",
    "analyze_telemetry",
    "apply_fault",
    "generate_telemetry",
    "inject_faults",
    "run_scenario",
    "verify_recovery",
]
