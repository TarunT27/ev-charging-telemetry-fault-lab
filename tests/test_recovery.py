import unittest

from telemetry_lab.models import ChargerState, DiagnosticFinding, RecoveryAction, TelemetrySample
from telemetry_lab.recovery import evaluate_recovery_safety, verify_recovery


def sample(
    sequence: int,
    *,
    connection_ok: bool = True,
    state: ChargerState = ChargerState.CHARGING,
    power_kw: float = 120.0,
    diagnostic_code: str = "OK",
) -> TelemetrySample:
    return TelemetrySample(
        charger_id="EVSE-001",
        session_id="SESSION-1",
        sequence=sequence,
        timestamp_ms=1_000 + sequence * 1_000,
        power_kw=power_kw,
        voltage_v=400.0,
        current_a=power_kw * 2.5,
        temperature_c=32.0,
        soc_percent=30.0 + sequence,
        charging_state=state,
        connection_ok=connection_ok,
        diagnostic_code=diagnostic_code,
    )


def finding(sequence: int, rule: str) -> DiagnosticFinding:
    return DiagnosticFinding("EVSE-001", sequence, 1_000 + sequence * 1_000, rule, "high", rule)


class ControllerRecoveryTests(unittest.TestCase):
    def test_network_loss_safe_stops_reconnects_health_checks_then_resumes(self):
        offline = sample(
            4,
            connection_ok=False,
            state=ChargerState.OFFLINE,
            power_kw=0.0,
        )
        healthy_retry = sample(4, state=ChargerState.RECOVERED)

        result = verify_recovery(
            (offline,),
            (finding(4, "connection-health"),),
            (healthy_retry,),
        )

        self.assertEqual(
            ["safe-stop", "reconnect", "health-check", "resume"],
            [action.action for action in result.actions],
        )
        self.assertEqual(["passed"] * 4, [action.outcome for action in result.actions])
        self.assertEqual((healthy_retry,), result.controller_samples)
        self.assertEqual(1, result.recovered_faults)
        self.assertEqual(1, result.reconnect_count)
        self.assertEqual(0, result.unsafe_actions)

    def test_reconnect_failure_blocks_resume_and_does_not_claim_recovery(self):
        offline = sample(4, connection_ok=False, state=ChargerState.OFFLINE, power_kw=0.0)
        still_offline = sample(4, connection_ok=False, state=ChargerState.OFFLINE, power_kw=0.0)

        result = verify_recovery(
            (offline,),
            (finding(4, "connection-health"),),
            (still_offline,),
        )

        outcomes = {(action.action, action.outcome) for action in result.actions}
        self.assertIn(("reconnect", "failed"), outcomes)
        self.assertIn(("health-check", "failed"), outcomes)
        self.assertIn(("resume", "blocked"), outcomes)
        self.assertEqual(0, result.recovered_faults)
        self.assertEqual(0, result.unsafe_actions)
        self.assertNotIn(still_offline, result.controller_samples)

    def test_missing_retry_exhausts_without_inventing_success(self):
        result = verify_recovery(
            (),
            (finding(2, "missing-sequence"),),
            (),
        )

        self.assertEqual(0, result.recovered_faults)
        self.assertEqual(1, result.retry_count)
        self.assertEqual("exhausted", result.actions[-1].outcome)
        self.assertEqual((), result.controller_samples)

    def test_corrupt_resend_must_be_valid_before_acceptance(self):
        corrupt = sample(3, power_kw=-1.0)
        invalid_retry = sample(3, diagnostic_code="")

        failed = verify_recovery(
            (corrupt,),
            (finding(3, "measurement-range"),),
            (invalid_retry,),
        )

        self.assertEqual(0, failed.recovered_faults)
        self.assertEqual("failed", failed.actions[-1].outcome)

        repaired = sample(3)
        recovered = verify_recovery(
            (corrupt,),
            (finding(3, "measurement-range"),),
            (repaired,),
        )
        self.assertEqual(1, recovered.recovered_faults)
        self.assertEqual((repaired,), recovered.controller_samples)

    def test_duplicate_and_late_packets_are_safely_isolated_without_oracle_labels(self):
        canonical = sample(5)
        duplicate = canonical.with_changes(timestamp_ms=canonical.timestamp_ms + 50)

        result = verify_recovery(
            (canonical, duplicate),
            (
                finding(5, "duplicate-packet"),
                finding(5, "latency-threshold"),
            ),
            (),
        )

        self.assertEqual(1, result.recovered_faults)
        self.assertEqual((canonical,), result.controller_samples)
        self.assertEqual(0, result.retry_count)

    def test_timing_fault_uses_canonical_buffered_sample(self):
        canonical = sample(5)
        delayed = canonical.with_changes(timestamp_ms=canonical.timestamp_ms + 2_000)

        result = verify_recovery(
            (delayed,),
            (finding(5, "latency-threshold"),),
            (canonical,),
        )

        self.assertEqual((canonical,), result.controller_samples)
        self.assertEqual(1, result.recovered_faults)
        self.assertEqual(0, result.unsafe_actions)

    def test_safety_evaluator_rejects_temporally_corrupt_controller_state(self):
        canonical = sample(5)
        shifted = canonical.with_changes(timestamp_ms=canonical.timestamp_ms - 2_000)

        self.assertEqual(
            1,
            evaluate_recovery_safety((), (shifted,), (canonical,)),
        )

    def test_independent_safety_evaluator_catches_early_resume(self):
        unsafe_log = (
            RecoveryAction("EVSE-001", 4, "resume", "passed", "resumed too early"),
            RecoveryAction("EVSE-001", 4, "health-check", "passed", "checked too late"),
        )

        self.assertEqual(1, evaluate_recovery_safety(unsafe_log, (sample(4),)))


if __name__ == "__main__":
    unittest.main()
