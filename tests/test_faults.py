import random
import unittest

from telemetry_lab.faults import apply_fault, inject_faults
from telemetry_lab.models import FaultProfile, FaultType, ScenarioConfig, TelemetrySample


def sample(sequence: int = 2) -> TelemetrySample:
    return TelemetrySample(
        charger_id="EVSE-001",
        session_id="session-1",
        sequence=sequence,
        timestamp_ms=1_700_000_002_000,
        power_kw=80.0,
        voltage_v=400.0,
        current_a=200.0,
        temperature_c=34.0,
        soc_percent=45.0,
    )


class FaultInjectionTests(unittest.TestCase):
    def test_timeout_drops_sample_without_mutating_input(self):
        original = sample()

        application = apply_fault(original, FaultType.TIMEOUT, random.Random(1))

        self.assertEqual((), application.samples)
        self.assertTrue(application.event.dropped)
        self.assertEqual(80.0, original.power_kw)

    def test_delay_corrupt_spike_duplicate_and_out_of_order_have_expected_effects(self):
        original = sample()

        delayed = apply_fault(original, FaultType.DELAY, random.Random(1), severity=2.0)
        corrupted = apply_fault(original, FaultType.CORRUPT, random.Random(1))
        spiked = apply_fault(original, FaultType.SPIKE, random.Random(1), severity=2.0)
        duplicated = apply_fault(original, FaultType.DUPLICATE, random.Random(1))
        reordered = apply_fault(original, FaultType.OUT_OF_ORDER, random.Random(1), severity=2.0)

        self.assertGreater(delayed.samples[0].timestamp_ms, original.timestamp_ms)
        self.assertLess(corrupted.samples[0].power_kw, 0.0)
        self.assertGreater(spiked.samples[0].power_kw, original.power_kw)
        self.assertEqual(2, len(duplicated.samples))
        self.assertLess(reordered.samples[0].timestamp_ms, original.timestamp_ms)

    def test_connection_drop_and_incomplete_message_expose_controller_health(self):
        original = sample()

        disconnected = apply_fault(original, FaultType.CONNECTION_DROP, random.Random(1))
        incomplete = apply_fault(original, FaultType.INCOMPLETE_MESSAGE, random.Random(1))

        self.assertFalse(disconnected.samples[0].connection_ok)
        self.assertEqual("offline", disconnected.samples[0].charging_state.value)
        self.assertEqual("", incomplete.samples[0].diagnostic_code)

    def test_consecutive_stuck_faults_freeze_the_same_observed_value(self):
        originals = tuple(sample(sequence=index).with_changes(power_kw=80.0 + index) for index in range(6))
        config = ScenarioConfig(
            name="frozen sensor",
            samples_per_charger=6,
            fault_profiles=(FaultProfile(FaultType.STUCK, rate=1.0),),
        )

        injection = inject_faults(originals, config)

        self.assertEqual(1, len({changed.power_kw for changed in injection.samples}))

    def test_seeded_pipeline_is_repeatable_and_records_ground_truth(self):
        originals = tuple(sample(sequence=index) for index in range(10))
        config = ScenarioConfig(
            name="all-timeouts",
            seed=7,
            samples_per_charger=10,
            fault_profiles=(FaultProfile(FaultType.TIMEOUT, rate=1.0),),
        )

        first = inject_faults(originals, config)
        second = inject_faults(originals, config)

        self.assertEqual(first, second)
        self.assertEqual(0, len(first.samples))
        self.assertEqual(10, len(first.events))


if __name__ == "__main__":
    unittest.main()
