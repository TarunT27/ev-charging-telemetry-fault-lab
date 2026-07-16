"""Explainable diagnostics and scenario-level reliability metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from telemetry_lab.models import (
    DiagnosticFinding,
    DiagnosticReport,
    FaultEvent,
    FaultType,
    ScenarioMetrics,
    TelemetrySample,
)

FAULT_RULES: dict[FaultType, frozenset[str]] = {
    FaultType.TIMEOUT: frozenset({"missing-sequence"}),
    FaultType.DELAY: frozenset({"latency-threshold"}),
    FaultType.CORRUPT: frozenset({"measurement-range"}),
    FaultType.SPIKE: frozenset({"power-spike", "electrical-consistency"}),
    FaultType.STUCK: frozenset({"sensor-freeze"}),
    FaultType.DUPLICATE: frozenset({"duplicate-packet"}),
    FaultType.OUT_OF_ORDER: frozenset({"timestamp-order"}),
    FaultType.CONNECTION_DROP: frozenset({"connection-health"}),
    FaultType.INCOMPLETE_MESSAGE: frozenset({"message-completeness"}),
}


def _finding(sample: TelemetrySample, rule: str, severity: str, message: str) -> DiagnosticFinding:
    return DiagnosticFinding(
        charger_id=sample.charger_id,
        sequence=sample.sequence,
        timestamp_ms=sample.timestamp_ms,
        rule=rule,
        severity=severity,
        message=message,
    )


def _range_findings(sample: TelemetrySample) -> tuple[DiagnosticFinding, ...]:
    messages: list[str] = []
    if not 0.0 <= sample.power_kw <= 450.0:
        messages.append(f"power {sample.power_kw:.1f} kW is outside [0, 450]")
    if not 200.0 <= sample.voltage_v <= 1_000.0:
        messages.append(f"voltage {sample.voltage_v:.1f} V is outside [200, 1000]")
    if not 0.0 <= sample.current_a <= 1_000.0:
        messages.append(f"current {sample.current_a:.1f} A is outside [0, 1000]")
    if not -40.0 <= sample.temperature_c <= 120.0:
        messages.append(f"temperature {sample.temperature_c:.1f} C is outside [-40, 120]")
    if not 0.0 <= sample.soc_percent <= 100.0:
        messages.append(f"state of charge {sample.soc_percent:.1f}% is outside [0, 100]")
    return tuple(_finding(sample, "measurement-range", "critical", message) for message in messages)


def _percentile_95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)]


def analyze_telemetry(
    samples: tuple[TelemetrySample, ...],
    events: tuple[FaultEvent, ...] = (),
    *,
    total_input: int | None = None,
    interval_ms: int = 1_000,
    expected_samples: tuple[TelemetrySample, ...] = (),
    recovered_keys: frozenset[tuple[str, int]] = frozenset(),
    retry_count: int = 0,
    reconnect_count: int = 0,
    unsafe_actions: int = 0,
) -> DiagnosticReport | tuple[DiagnosticFinding, ...]:
    """Detect telemetry anomalies and compare exact rules with fault ground truth."""

    findings: list[DiagnosticFinding] = []
    previous_by_charger: dict[str, TelemetrySample] = {}
    repeated_values: dict[str, int] = defaultdict(int)
    seen_keys: set[tuple[str, int]] = set()
    expected_by_key = {(sample.charger_id, sample.sequence): sample for sample in expected_samples}
    observed_keys = {(sample.charger_id, sample.sequence) for sample in samples}

    for key in sorted(expected_by_key.keys() - observed_keys):
        missing = expected_by_key[key]
        findings.append(_finding(missing, "missing-sequence", "high", "expected telemetry sequence was not received"))

    for sample in samples:
        findings.extend(_range_findings(sample))
        key = (sample.charger_id, sample.sequence)
        expected = expected_by_key.get(key)
        if expected is not None:
            if sample.timestamp_ms > expected.timestamp_ms + interval_ms:
                findings.append(_finding(sample, "latency-threshold", "high", "telemetry exceeded the delivery deadline"))
            if sample.timestamp_ms < expected.timestamp_ms:
                findings.append(_finding(sample, "timestamp-order", "high", "timestamp regressed behind its expected slot"))
        if key in seen_keys:
            findings.append(_finding(sample, "duplicate-packet", "high", "sequence number was observed more than once"))
        seen_keys.add(key)

        if not sample.connection_ok:
            findings.append(_finding(sample, "connection-health", "critical", "controller connection reported offline"))
        if not sample.diagnostic_code.strip():
            findings.append(_finding(sample, "message-completeness", "high", "required diagnostic code is missing"))

        previous = previous_by_charger.get(sample.charger_id)
        if previous is not None:
            if sample.timestamp_ms <= previous.timestamp_ms and not any(
                finding.rule == "timestamp-order" and (finding.charger_id, finding.sequence) == key
                for finding in findings
            ):
                findings.append(_finding(sample, "timestamp-order", "high", "timestamp did not advance monotonically"))
            power_delta = abs(sample.power_kw - (expected.power_kw if expected is not None else previous.power_kw))
            if power_delta > 120.0:
                findings.append(_finding(sample, "power-spike", "high", f"power deviated by {power_delta:.1f} kW from baseline"))
            if sample.power_kw == previous.power_kw and sample.soc_percent == previous.soc_percent:
                repeated_values[sample.charger_id] += 1
                if repeated_values[sample.charger_id] >= 1:
                    findings.append(_finding(sample, "sensor-freeze", "medium", "multiple sensor fields remained unchanged"))
            else:
                repeated_values[sample.charger_id] = 0

        expected_power = sample.voltage_v * sample.current_a / 1_000.0
        if sample.power_kw >= 0.0 and abs(expected_power - sample.power_kw) > max(5.0, sample.power_kw * 0.15):
            findings.append(_finding(sample, "electrical-consistency", "medium", "reported power does not match voltage x current"))
        previous_by_charger[sample.charger_id] = sample

    ordered_findings = tuple(findings)
    if total_input is None and not events:
        return ordered_findings

    rules_by_key: dict[tuple[str, int], set[str]] = defaultdict(set)
    for finding in ordered_findings:
        rules_by_key[(finding.charger_id, finding.sequence)].add(finding.rule)
    detected_events = sum(
        bool(rules_by_key[(event.charger_id, event.sequence)] & FAULT_RULES[event.fault_type])
        for event in events
    )
    rejected_keys = {
        (finding.charger_id, finding.sequence)
        for finding in ordered_findings
        if finding.severity in {"high", "critical"}
    }
    rejected = sum((sample.charger_id, sample.sequence) in rejected_keys for sample in samples)
    total = len(samples) if total_input is None else total_input
    delays = [
        int(event.detail.split(" ")[3])
        for event in events
        if event.fault_type is FaultType.DELAY and event.detail.split(" ")[3].isdigit()
    ]
    non_negative_power = [sample.power_kw for sample in samples if sample.power_kw >= 0]
    recovered_faults = sum((event.charger_id, event.sequence) in recovered_keys for event in events)
    metrics = ScenarioMetrics(
        total_input=total,
        total_output=len(samples),
        accepted=max(0, len(samples) - rejected),
        rejected=rejected,
        dropped=sum(event.dropped for event in events),
        injected_faults=len(events),
        detected_faults=detected_events,
        detection_rate=round(detected_events / len(events), 4) if events else 1.0,
        average_power_kw=round(mean(non_negative_power), 3) if non_negative_power else 0.0,
        energy_kwh=round(sum(non_negative_power) * interval_ms / 3_600_000.0, 3),
        p95_delay_ms=_percentile_95(delays),
        recovered_faults=recovered_faults,
        recovery_rate=round(recovered_faults / len(events), 4) if events else 1.0,
        retry_count=retry_count,
        reconnect_count=reconnect_count,
        unsafe_actions=unsafe_actions,
    )
    return DiagnosticReport(findings=ordered_findings, metrics=metrics)
