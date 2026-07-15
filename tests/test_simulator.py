import unittest

from telemetry_lab.simulator import (
    FaultType,
    TelemetrySample,
    apply_fault,
    run_scenario,
    validate_sample,
)


class TelemetrySimulatorTests(unittest.TestCase):
    def setUp(self):
        self.sample = TelemetrySample(charger_id="charger-1", power_kw=120.0, timestamp_ms=1000)

    def test_timeout_drops_sample(self):
        self.assertIsNone(apply_fault(self.sample, FaultType.TIMEOUT))

    def test_delay_returns_new_sample(self):
        delayed = apply_fault(self.sample, FaultType.DELAY, delay_ms=500)

        self.assertEqual(1500, delayed.timestamp_ms)
        self.assertEqual(1000, self.sample.timestamp_ms)

    def test_corruption_is_detected(self):
        corrupted = apply_fault(self.sample, FaultType.CORRUPT)

        self.assertFalse(validate_sample(corrupted))

    def test_scenario_counts_valid_and_rejected_samples(self):
        result = run_scenario((self.sample, self.sample), FaultType.CORRUPT)

        self.assertEqual({"accepted": 0, "rejected": 2, "dropped": 0}, result)


if __name__ == "__main__":
    unittest.main()
