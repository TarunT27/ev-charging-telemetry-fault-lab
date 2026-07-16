"""Command-line interface for repeatable lab runs and local dashboard serving."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from telemetry_lab.exporters import export_result
from telemetry_lab.models import ScenarioResult
from telemetry_lab.presets import PRESETS, config_from_preset
from telemetry_lab.service import run_scenario


def _bounded_integer(minimum: int, maximum: int, label: str) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{label} must be an integer") from error
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"{label} must be between {minimum} and {maximum}")
        return parsed

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ev-fault-lab",
        description="Run deterministic EV charging telemetry fault-injection scenarios.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    def add_run_arguments(command: argparse.ArgumentParser, default_preset: str) -> None:
        command.add_argument("--preset", choices=tuple(PRESETS), default=default_preset)
        command.add_argument("--name", default=None)
        command.add_argument("--seed", type=int, default=27)
        command.add_argument("--chargers", type=_bounded_integer(1, 20, "chargers"), default=3)
        command.add_argument("--samples", type=_bounded_integer(5, 1000, "samples"), default=60)
        command.add_argument("--output-dir", type=Path, default=Path("artifacts"))

    add_run_arguments(subcommands.add_parser("demo", help="run the curated mixed-fault demo"), "mixed-faults")
    add_run_arguments(subcommands.add_parser("run", help="run a configurable preset"), "baseline")
    subcommands.add_parser("list-presets", help="list bundled scenario presets")
    serve = subcommands.add_parser("serve", help="launch the interactive local dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=_bounded_integer(1, 65535, "port"), default=8000)
    return parser


def _print_summary(result: ScenarioResult, paths: tuple[Path, Path, Path]) -> None:
    metrics = result.report.metrics
    print(f"\n  {result.config.name}")
    print(f"  {'-' * min(54, len(result.config.name) + 18)}")
    print(f"  Samples        {metrics.total_input:>7}")
    print(f"  Injected       {metrics.injected_faults:>7}")
    print(f"  Detected       {metrics.detected_faults:>7}")
    print(f"  Detection rate {metrics.detection_rate * 100:>6.1f}%")
    print(f"  Recovery rate  {metrics.recovery_rate * 100:>6.1f}%")
    print(f"  Reconnects      {metrics.reconnect_count:>7}")
    print(f"  Unsafe actions  {metrics.unsafe_actions:>7}")
    print(f"  Energy         {metrics.energy_kwh:>6.1f} kWh")
    print("\n  Artifacts")
    for path in paths:
        print(f"  - {path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "list-presets":
        for preset, profiles in PRESETS.items():
            faults = ", ".join(profile.fault_type.value for profile in profiles) or "none"
            print(f"{preset:16} {faults}")
        return 0
    if arguments.command == "serve":
        import uvicorn

        uvicorn.run("telemetry_lab.api:create_app", factory=True, host=arguments.host, port=arguments.port)
        return 0

    try:
        config = config_from_preset(
            arguments.preset,
            name=arguments.name,
            seed=arguments.seed,
            charger_count=arguments.chargers,
            samples_per_charger=arguments.samples,
        )
        result = run_scenario(config)
        paths = export_result(result, arguments.output_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    _print_summary(result, paths)
    return 0
