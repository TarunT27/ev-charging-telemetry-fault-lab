"""Seeded synthetic EV charging telemetry generation."""

from __future__ import annotations

import math
import random

from telemetry_lab.models import ChargerState, ScenarioConfig, TelemetrySample


def generate_telemetry(config: ScenarioConfig) -> tuple[TelemetrySample, ...]:
    """Generate realistic, repeatable DC fast-charging curves."""

    randomizer = random.Random(config.seed)
    generated: list[TelemetrySample] = []
    for charger_index in range(config.charger_count):
        charger_id = f"EVSE-{charger_index + 1:03d}"
        rated_power = 120.0 + charger_index * 10.0
        initial_soc = 12.0 + randomizer.uniform(0.0, 8.0)
        for sequence in range(config.samples_per_charger):
            progress = sequence / max(config.samples_per_charger - 1, 1)
            ramp_intervals = max(3, round(config.samples_per_charger * 0.12))
            ramp = min(sequence / ramp_intervals, 1.0)
            taper = 1.0 if progress < 0.68 else max(0.18, 1.0 - (progress - 0.68) * 2.4)
            power_kw = max(0.0, rated_power * ramp * taper + randomizer.uniform(-1.8, 1.8))
            voltage_v = 360.0 + 105.0 * progress + randomizer.uniform(-1.5, 1.5)
            current_a = power_kw * 1_000.0 / voltage_v
            temperature_c = 24.0 + power_kw * 0.075 + 2.0 * math.sin(progress * math.pi)
            soc_percent = min(96.0, initial_soc + progress * (78.0 - initial_soc))
            generated.append(
                TelemetrySample(
                    charger_id=charger_id,
                    session_id=f"SESSION-{config.seed}-{charger_index + 1:03d}",
                    sequence=sequence,
                    timestamp_ms=config.start_timestamp_ms + sequence * config.interval_ms,
                    power_kw=round(power_kw, 3),
                    voltage_v=round(voltage_v, 3),
                    current_a=round(current_a, 3),
                    temperature_c=round(temperature_c, 3),
                    soc_percent=round(soc_percent, 3),
                    charging_state=ChargerState.CONNECTED if sequence == 0 else ChargerState.CHARGING,
                    connection_ok=True,
                    diagnostic_code="OK",
                )
            )
    return tuple(generated)
