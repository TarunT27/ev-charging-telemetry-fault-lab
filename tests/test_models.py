import math
import unittest

from telemetry_lab.models import FaultProfile, FaultType, ScenarioConfig, TelemetrySample


class ScenarioConfigTests(unittest.TestCase):
    def test_config_is_immutable_and_validates_bounds(self):
        config = ScenarioConfig(name="Mixed lab", seed=27, charger_count=3, samples_per_charger=20)

        with self.assertRaises(AttributeError):
            config.seed = 99  # type: ignore[misc]
        with self.assertRaises(ValueError):
            ScenarioConfig(name="", charger_count=1)
        with self.assertRaises(ValueError):
            ScenarioConfig(name="oversized", charger_count=21)
        with self.assertRaises(ValueError):
            FaultProfile(FaultType.SPIKE, rate=1.1)

    def test_sample_rejects_non_finite_measurements(self):
        with self.assertRaises(ValueError):
            TelemetrySample(
                charger_id="charger-1",
                session_id="session-1",
                sequence=0,
                timestamp_ms=1_700_000_000_000,
                power_kw=math.nan,
                voltage_v=400.0,
                current_a=100.0,
                temperature_c=25.0,
                soc_percent=20.0,
            )


if __name__ == "__main__":
    unittest.main()
