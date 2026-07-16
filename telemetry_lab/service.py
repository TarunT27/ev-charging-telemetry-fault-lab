"""Application service for complete telemetry scenarios."""

from __future__ import annotations

from telemetry_lab.diagnostics import analyze_telemetry
from telemetry_lab.faults import inject_faults
from telemetry_lab.generator import generate_telemetry
from telemetry_lab.models import DiagnosticReport, ScenarioConfig, ScenarioResult
from telemetry_lab.recovery import verify_recovery


def run_scenario(config: ScenarioConfig) -> ScenarioResult:
    """Generate, fault, diagnose, and summarize one deterministic scenario."""

    original = generate_telemetry(config)
    injection = inject_faults(original, config)
    detected = analyze_telemetry(
        injection.samples,
        expected_samples=original,
        interval_ms=config.interval_ms,
    )
    if not isinstance(detected, tuple):  # pragma: no cover - call contract
        raise RuntimeError("scenario detection did not return findings")
    recovery = verify_recovery(injection.samples, detected, original)
    report = analyze_telemetry(
        injection.samples,
        injection.events,
        total_input=len(original),
        interval_ms=config.interval_ms,
        expected_samples=original,
        recovered_keys=recovery.recovered_keys,
        retry_count=recovery.retry_count,
        reconnect_count=recovery.reconnect_count,
        unsafe_actions=recovery.unsafe_actions,
    )
    if not isinstance(report, DiagnosticReport):  # pragma: no cover - call contract
        raise RuntimeError("scenario diagnostics did not return a report")
    return ScenarioResult(
        config=config,
        original_samples=original,
        observed_samples=injection.samples,
        controller_samples=recovery.controller_samples,
        events=injection.events,
        recovery_actions=recovery.actions,
        report=report,
    )
