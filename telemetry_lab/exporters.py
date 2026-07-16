"""Safe, explicit artifact exporters."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from telemetry_lab.models import ScenarioResult
from telemetry_lab.report import render_html_report


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def export_result(result: ScenarioResult, output_dir: Path) -> tuple[Path, Path, Path]:
    """Write JSON, CSV, and HTML artifacts atomically."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(character if character.isalnum() else "-" for character in result.config.name.lower()).strip("-")
    slug = slug[:60] or "scenario"
    json_path = output_dir / f"{slug}.json"
    csv_path = output_dir / f"{slug}.csv"
    html_path = output_dir / f"{slug}.html"
    _atomic_text_write(json_path, result.to_json() + "\n")
    _atomic_text_write(html_path, render_html_report(result))

    rows = [
        [
            sample.charger_id,
            sample.session_id,
            sample.sequence,
            sample.timestamp_ms,
            sample.power_kw,
            sample.voltage_v,
            sample.current_a,
            sample.temperature_c,
            sample.soc_percent,
            sample.charging_state.value,
            sample.connection_ok,
            sample.diagnostic_code,
        ]
        for sample in result.observed_samples
    ]
    with tempfile.TemporaryDirectory(dir=output_dir) as temporary_dir:
        temporary_path = Path(temporary_dir) / csv_path.name
        with temporary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("charger_id", "session_id", "sequence", "timestamp_ms", "power_kw", "voltage_v", "current_a", "temperature_c", "soc_percent", "charging_state", "connection_ok", "diagnostic_code"))
            writer.writerows(rows)
        os.replace(temporary_path, csv_path)
    return json_path, csv_path, html_path
