"""Curated scenario presets used by the CLI and dashboard."""

from __future__ import annotations

from telemetry_lab.models import FaultProfile, FaultType, ScenarioConfig

PRESETS: dict[str, tuple[FaultProfile, ...]] = {
    "baseline": (),
    "noisy-network": (
        FaultProfile(FaultType.DELAY, rate=0.16, severity=1.3),
        FaultProfile(FaultType.TIMEOUT, rate=0.08),
        FaultProfile(FaultType.CONNECTION_DROP, rate=0.06),
        FaultProfile(FaultType.DUPLICATE, rate=0.06),
        FaultProfile(FaultType.OUT_OF_ORDER, rate=0.05),
    ),
    "sensor-drift": (
        FaultProfile(FaultType.SPIKE, rate=0.12, severity=1.2),
        FaultProfile(FaultType.CORRUPT, rate=0.08),
        FaultProfile(FaultType.INCOMPLETE_MESSAGE, rate=0.06),
        FaultProfile(FaultType.STUCK, rate=0.12),
    ),
    "mixed-faults": (
        FaultProfile(FaultType.DELAY, rate=0.09),
        FaultProfile(FaultType.TIMEOUT, rate=0.05),
        FaultProfile(FaultType.CORRUPT, rate=0.05),
        FaultProfile(FaultType.SPIKE, rate=0.07),
        FaultProfile(FaultType.STUCK, rate=0.06),
        FaultProfile(FaultType.DUPLICATE, rate=0.04),
        FaultProfile(FaultType.OUT_OF_ORDER, rate=0.04),
        FaultProfile(FaultType.CONNECTION_DROP, rate=0.04),
        FaultProfile(FaultType.INCOMPLETE_MESSAGE, rate=0.04),
    ),
}


def config_from_preset(
    preset: str,
    *,
    name: str | None = None,
    seed: int = 27,
    charger_count: int = 3,
    samples_per_charger: int = 60,
) -> ScenarioConfig:
    try:
        profiles = PRESETS[preset]
    except KeyError as error:
        choices = ", ".join(PRESETS)
        raise ValueError(f"unknown preset {preset!r}; choose from {choices}") from error
    return ScenarioConfig(
        name=name or preset.replace("-", " ").title(),
        seed=seed,
        charger_count=charger_count,
        samples_per_charger=samples_per_charger,
        fault_profiles=profiles,
    )


def preset_catalog() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": preset,
            "name": preset.replace("-", " ").title(),
            "faults": [profile.fault_type.value for profile in profiles],
            "combined_rate": round(sum(profile.rate for profile in profiles), 2),
        }
        for preset, profiles in PRESETS.items()
    )
