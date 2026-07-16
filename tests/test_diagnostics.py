import unittest

from telemetry_lab.diagnostics import analyze_telemetry
from telemetry_lab.faults import FaultInjectionResult
from telemetry_lab.generator import generate_telemetry
from telemetry_lab.models import FaultEvent, FaultType, ScenarioConfig


class DiagnosticsTests(unittest.TestCase):
    def test_detects_invalid_measurement_and_timestamp_regression(self):
        samples = generate_telemetry(ScenarioConfig(name="crafted", samples_per_charger=6))
        invalid = samples[2].with_changes(power_kw=-10.0)
        regressed = samples[4].with_changes(timestamp_ms=samples[3].timestamp_ms - 1)
        observed = (*samples[:2], invalid, *samples[3:4], regressed, *samples[5:])

        findings = analyze_telemetry(observed)

        rules = {finding.rule for finding in findings}
        self.assertIn("measurement-range", rules)
        self.assertIn("timestamp-order", rules)

    def test_scenario_metrics_distinguish_injected_and_detected_faults(self):
        samples = generate_telemetry(ScenarioConfig(name="metrics", samples_per_charger=5))
        event = FaultEvent(
            charger_id=samples[0].charger_id,
            sequence=samples[0].sequence,
            fault_type=FaultType.CORRUPT,
            detail="negative power",
            dropped=False,
        )
        injection = FaultInjectionResult(
            samples=(samples[0].with_changes(power_kw=-1.0), *samples[1:]),
            events=(event,),
        )

        report = analyze_telemetry(injection.samples, injection.events, total_input=len(samples))

        self.assertEqual(1, report.metrics.injected_faults)
        self.assertEqual(1, report.metrics.detected_faults)
        self.assertEqual(1.0, report.metrics.detection_rate)
        self.assertEqual(len(samples), report.metrics.total_input)

    def test_energy_scales_with_configured_sample_interval(self):
        samples = generate_telemetry(ScenarioConfig(name="energy", samples_per_charger=5))

        fast = analyze_telemetry(samples, total_input=len(samples), interval_ms=100)
        slow = analyze_telemetry(samples, total_input=len(samples), interval_ms=10_000)

        self.assertAlmostEqual(fast.metrics.energy_kwh * 100, slow.metrics.energy_kwh, places=1)


if __name__ == "__main__":
    unittest.main()
