import unittest

from telemetry_lab.diagnostics import analyze_telemetry
from telemetry_lab.generator import generate_telemetry
from telemetry_lab.models import ScenarioConfig


class TelemetryGeneratorTests(unittest.TestCase):
    def test_generation_is_deterministic_and_charging_curve_is_plausible(self):
        config = ScenarioConfig(name="baseline", seed=42, charger_count=2, samples_per_charger=12)

        first = generate_telemetry(config)
        second = generate_telemetry(config)

        self.assertEqual(first, second)
        self.assertEqual(24, len(first))
        self.assertEqual({"EVSE-001", "EVSE-002"}, {sample.charger_id for sample in first})
        self.assertTrue(all(0.0 <= sample.soc_percent <= 100.0 for sample in first))
        self.assertTrue(all(sample.timestamp_ms >= config.start_timestamp_ms for sample in first))
        self.assertTrue(all(sample.connection_ok for sample in first))
        self.assertTrue(all(sample.diagnostic_code == "OK" for sample in first))

    def test_maximum_supported_baseline_has_no_false_anomalies(self):
        samples = generate_telemetry(
            ScenarioConfig(name="maximum healthy fleet", charger_count=20, samples_per_charger=5)
        )

        self.assertEqual((), analyze_telemetry(samples, expected_samples=samples))


if __name__ == "__main__":
    unittest.main()
