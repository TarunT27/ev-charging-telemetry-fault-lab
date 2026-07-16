"""Pure, seeded fault injectors with ground-truth event recording."""

from __future__ import annotations

import random
from dataclasses import dataclass

from telemetry_lab.models import ChargerState, FaultEvent, FaultType, ScenarioConfig, TelemetrySample


@dataclass(frozen=True, slots=True)
class FaultApplication:
    samples: tuple[TelemetrySample, ...]
    event: FaultEvent


@dataclass(frozen=True, slots=True)
class FaultInjectionResult:
    samples: tuple[TelemetrySample, ...]
    events: tuple[FaultEvent, ...]


def apply_fault(
    sample: TelemetrySample,
    fault_type: FaultType,
    randomizer: random.Random | None = None,
    *,
    severity: float = 1.0,
    previous: TelemetrySample | None = None,
) -> FaultApplication:
    """Apply one fault and return new samples plus an auditable event."""

    rng = randomizer or random.Random(0)
    if severity <= 0:
        raise ValueError("severity must be positive")

    if fault_type is FaultType.TIMEOUT:
        changed: tuple[TelemetrySample, ...] = ()
        detail = "sample dropped after simulated transport timeout"
    elif fault_type is FaultType.DELAY:
        delay_ms = max(1, round(1_500 * severity + rng.randint(0, 500)))
        changed = (sample.with_changes(timestamp_ms=sample.timestamp_ms + delay_ms),)
        detail = f"delivery delayed by {delay_ms} ms"
    elif fault_type is FaultType.CORRUPT:
        changed = (sample.with_changes(power_kw=-abs(sample.power_kw) - severity),)
        detail = "power field corrupted to an impossible negative value"
    elif fault_type is FaultType.SPIKE:
        multiplier = 1.0 + 2.5 * severity
        changed = (sample.with_changes(power_kw=round(sample.power_kw * multiplier + 80.0, 3)),)
        detail = f"power spike injected at {multiplier:.1f}x baseline"
    elif fault_type is FaultType.STUCK:
        source = previous or sample
        changed = (
            sample.with_changes(
                power_kw=source.power_kw,
                voltage_v=source.voltage_v,
                current_a=source.current_a,
                temperature_c=source.temperature_c,
                soc_percent=source.soc_percent,
            ),
        )
        detail = "sensor fields frozen at the previous reading"
    elif fault_type is FaultType.DUPLICATE:
        changed = (sample, sample)
        detail = "packet duplicated with identical sequence number"
    elif fault_type is FaultType.OUT_OF_ORDER:
        shift_ms = max(1, round(2_000 * severity))
        changed = (sample.with_changes(timestamp_ms=max(0, sample.timestamp_ms - shift_ms)),)
        detail = f"timestamp shifted backward by {shift_ms} ms"
    elif fault_type is FaultType.CONNECTION_DROP:
        changed = (
            sample.with_changes(
                power_kw=0.0,
                current_a=0.0,
                charging_state=ChargerState.OFFLINE,
                connection_ok=False,
                diagnostic_code="NETWORK_LOSS",
            ),
        )
        detail = "controller link dropped; charging output inhibited"
    elif fault_type is FaultType.INCOMPLETE_MESSAGE:
        changed = (sample.with_changes(diagnostic_code=""),)
        detail = "diagnostic field removed from the telemetry message"
    else:  # pragma: no cover - enum makes this defensive only
        raise ValueError(f"unsupported fault: {fault_type}")

    return FaultApplication(
        samples=changed,
        event=FaultEvent(
            charger_id=sample.charger_id,
            sequence=sample.sequence,
            fault_type=fault_type,
            detail=detail,
            dropped=not changed,
        ),
    )


def inject_faults(samples: tuple[TelemetrySample, ...], config: ScenarioConfig) -> FaultInjectionResult:
    """Inject configured faults deterministically across an immutable stream."""

    rng = random.Random(config.seed + 10_007)
    observed: list[TelemetrySample] = []
    events: list[FaultEvent] = []
    previous_by_charger: dict[str, TelemetrySample] = {}
    for sample in samples:
        roll = rng.random()
        cumulative = 0.0
        selected = None
        for profile in config.fault_profiles:
            cumulative += profile.rate
            if roll < cumulative:
                selected = profile
                break
        previous = previous_by_charger.get(sample.charger_id)
        if selected is not None and selected.fault_type is FaultType.STUCK and previous is None:
            observed.append(sample)
            previous_by_charger[sample.charger_id] = sample
            continue
        if selected is None:
            observed.append(sample)
            previous_by_charger[sample.charger_id] = sample
        else:
            application = apply_fault(
                sample,
                selected.fault_type,
                rng,
                severity=selected.severity,
                previous=previous,
            )
            observed.extend(application.samples)
            events.append(application.event)
            if application.samples:
                previous_by_charger[sample.charger_id] = application.samples[-1]
    return FaultInjectionResult(samples=tuple(observed), events=tuple(events))
