"""Stateful recovery policy driven only by controller-observable diagnostics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise

from telemetry_lab.models import ChargerState, DiagnosticFinding, RecoveryAction, TelemetrySample

IncidentKey = tuple[str, int]

RESEND_RULES = frozenset(
    {
        "measurement-range",
        "message-completeness",
        "power-spike",
        "electrical-consistency",
        "sensor-freeze",
    }
)
BUFFER_RULES = frozenset({"duplicate-packet", "latency-threshold", "timestamp-order"})


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    actions: tuple[RecoveryAction, ...]
    controller_samples: tuple[TelemetrySample, ...]
    recovered_keys: frozenset[IncidentKey]
    recovered_faults: int
    retry_count: int
    reconnect_count: int
    unsafe_actions: int


def _action(key: IncidentKey, action: str, outcome: str, detail: str) -> RecoveryAction:
    return RecoveryAction(key[0], key[1], action, outcome, detail)


def _is_safe(sample: TelemetrySample) -> bool:
    expected_power = sample.voltage_v * sample.current_a / 1_000.0
    return all(
        (
            sample.connection_ok,
            sample.charging_state not in {ChargerState.OFFLINE, ChargerState.RECONNECTING},
            bool(sample.diagnostic_code.strip()),
            0.0 <= sample.power_kw <= 450.0,
            200.0 <= sample.voltage_v <= 1_000.0,
            0.0 <= sample.current_a <= 1_000.0,
            -40.0 <= sample.temperature_c <= 120.0,
            0.0 <= sample.soc_percent <= 100.0,
            abs(expected_power - sample.power_kw) <= max(5.0, sample.power_kw * 0.15),
        )
    )


def _is_repaired(
    candidate: TelemetrySample,
    observed: tuple[TelemetrySample, ...],
    rules: frozenset[str],
) -> bool:
    if not _is_safe(candidate):
        return False
    if not observed:
        return True
    faulty = observed[-1]
    if "sensor-freeze" in rules:
        return (candidate.power_kw, candidate.soc_percent) != (faulty.power_kw, faulty.soc_percent)
    if rules & {"measurement-range", "message-completeness", "power-spike", "electrical-consistency"}:
        return candidate != faulty
    return True


def evaluate_recovery_safety(
    actions: tuple[RecoveryAction, ...],
    controller_samples: tuple[TelemetrySample, ...],
    reference_samples: tuple[TelemetrySample, ...] = (),
) -> int:
    """Independently count violated safe-stop, transition, and acceptance invariants."""

    violations = sum(not _is_safe(sample) for sample in controller_samples)
    reference_by_key = {(sample.charger_id, sample.sequence): sample for sample in reference_samples}
    violations += sum(
        reference is not None and sample.timestamp_ms != reference.timestamp_ms
        for sample in controller_samples
        if (reference := reference_by_key.get((sample.charger_id, sample.sequence))) is not None
    )
    samples_by_charger: dict[str, list[TelemetrySample]] = defaultdict(list)
    for sample in controller_samples:
        samples_by_charger[sample.charger_id].append(sample)
    for charger_samples in samples_by_charger.values():
        ordered = sorted(charger_samples, key=lambda item: item.sequence)
        violations += sum(
            current.timestamp_ms <= previous.timestamp_ms
            for previous, current in pairwise(ordered)
        )
    actions_by_key: dict[IncidentKey, list[RecoveryAction]] = defaultdict(list)
    for action in actions:
        actions_by_key[(action.charger_id, action.sequence)].append(action)

    required_resume_order = ("safe-stop", "reconnect", "health-check", "resume")
    for incident_actions in actions_by_key.values():
        violations += sum(
            action.action == "safe-stop" and action.outcome != "passed" for action in incident_actions
        )
        passed_names = tuple(action.action for action in incident_actions if action.outcome == "passed")
        if "resume" in passed_names:
            positions = tuple(
                passed_names.index(required_action)
                if required_action in passed_names
                else len(passed_names)
                for required_action in required_resume_order
            )
            violations += positions != tuple(sorted(positions)) or any(
                required_action not in passed_names for required_action in required_resume_order
            )
    return int(violations)


def verify_recovery(
    observed_samples: tuple[TelemetrySample, ...],
    findings: tuple[DiagnosticFinding, ...],
    retry_samples: tuple[TelemetrySample, ...],
) -> RecoveryResult:
    """Execute a fail-closed controller policy without consuming injection labels.

    ``retry_samples`` models replies from the virtual charger after a bounded resend
    or reconnect request. Fault events remain ground truth for scoring only and are
    intentionally absent from this interface.
    """

    observed_by_key: dict[IncidentKey, list[TelemetrySample]] = defaultdict(list)
    for sample in observed_samples:
        observed_by_key[(sample.charger_id, sample.sequence)].append(sample)
    retry_by_key = {(sample.charger_id, sample.sequence): sample for sample in retry_samples}

    rules_by_key: dict[IncidentKey, set[str]] = defaultdict(set)
    for finding in findings:
        rules_by_key[(finding.charger_id, finding.sequence)].add(finding.rule)

    incident_keys = frozenset(rules_by_key)
    accepted: dict[IncidentKey, TelemetrySample] = {}
    for key, samples in observed_by_key.items():
        if key not in incident_keys and _is_safe(samples[0]):
            accepted[key] = samples[0]

    actions: list[RecoveryAction] = []
    recovered_faults = 0
    recovered_keys: set[IncidentKey] = set()
    retry_count = 0
    reconnect_count = 0

    for key in sorted(incident_keys):
        rules = frozenset(rules_by_key[key])
        observed = tuple(observed_by_key.get(key, ()))
        retry = retry_by_key.get(key)

        if "connection-health" in rules:
            safely_inhibited = bool(observed) and all(
                sample.power_kw == 0.0
                and sample.current_a == 0.0
                and sample.charging_state is ChargerState.OFFLINE
                for sample in observed
            )
            actions.append(
                _action(
                    key,
                    "safe-stop",
                    "passed" if safely_inhibited else "failed",
                    "charging output verified inhibited before reconnect",
                )
            )
            reconnect_count += 1
            reconnect_ok = retry is not None and _is_safe(retry)
            actions.append(
                _action(
                    key,
                    "reconnect",
                    "passed" if reconnect_ok else "failed",
                    "virtual controller reconnect handshake validated" if reconnect_ok else "reconnect did not return a healthy session",
                )
            )
            actions.append(
                _action(
                    key,
                    "health-check",
                    "passed" if reconnect_ok else "failed",
                    "connection and telemetry invariants checked before resume",
                )
            )
            actions.append(
                _action(
                    key,
                    "resume",
                    "passed" if reconnect_ok and safely_inhibited else "blocked",
                    "charging resumed after health checks" if reconnect_ok and safely_inhibited else "fail-closed policy prevented early resume",
                )
            )
            if reconnect_ok and safely_inhibited and retry is not None:
                accepted[key] = retry
                recovered_faults += 1
                recovered_keys.add(key)
            continue

        if "missing-sequence" in rules:
            retry_count += 1
            retry_ok = retry is not None and _is_safe(retry)
            actions.append(
                _action(
                    key,
                    "retry",
                    "passed" if retry_ok else "exhausted",
                    "missing sequence recovered and validated" if retry_ok else "bounded retry returned no valid telemetry",
                )
            )
            if retry_ok and retry is not None:
                accepted[key] = retry
                recovered_faults += 1
                recovered_keys.add(key)
            continue

        if "duplicate-packet" in rules or (rules & BUFFER_RULES and not rules & RESEND_RULES):
            candidate = observed[0] if "duplicate-packet" in rules and observed else retry
            buffer_ok = candidate is not None and _is_safe(candidate)
            actions.append(
                _action(
                    key,
                    "reorder-buffer" if "duplicate-packet" not in rules else "deduplicate",
                    "passed" if buffer_ok else "failed",
                    "canonical packet isolated from live control state" if buffer_ok else "no valid packet remained after isolation",
                )
            )
            if buffer_ok and candidate is not None:
                accepted[key] = candidate
                recovered_faults += 1
                recovered_keys.add(key)
            continue

        if rules & RESEND_RULES:
            actions.append(
                _action(key, "reject-message", "passed", "anomalous telemetry excluded from control decisions")
            )
            retry_count += 1
            retry_ok = retry is not None and _is_repaired(retry, observed, rules)
            actions.append(
                _action(
                    key,
                    "request-resend",
                    "passed" if retry_ok else "failed",
                    "replacement telemetry passed validation" if retry_ok else "replacement telemetry failed validation",
                )
            )
            if retry_ok and retry is not None:
                accepted[key] = retry
                recovered_faults += 1
                recovered_keys.add(key)
            continue

        actions.append(_action(key, "flag-diagnostic", "failed", "no automatic recovery policy exists for this rule"))

    controller_samples = tuple(accepted[key] for key in sorted(accepted))
    unsafe_actions = evaluate_recovery_safety(tuple(actions), controller_samples, retry_samples)
    return RecoveryResult(
        actions=tuple(actions),
        controller_samples=controller_samples,
        recovered_keys=frozenset(recovered_keys),
        recovered_faults=recovered_faults,
        retry_count=retry_count,
        reconnect_count=reconnect_count,
        unsafe_actions=unsafe_actions,
    )
