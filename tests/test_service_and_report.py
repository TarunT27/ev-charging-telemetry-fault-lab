import json
import unittest
from dataclasses import replace

from telemetry_lab.diagnostics import analyze_telemetry
from telemetry_lab.models import FaultEvent, FaultProfile, FaultType, RecoveryAction, ScenarioConfig
from telemetry_lab.report import render_html_report
from telemetry_lab.service import run_scenario


class ScenarioServiceTests(unittest.TestCase):
    def test_every_fault_is_detected_and_recovers_without_unsafe_actions(self):
        for fault_type in FaultType:
            with self.subTest(fault_type=fault_type):
                result = run_scenario(
                    ScenarioConfig(
                        name=fault_type.value,
                        samples_per_charger=20,
                        fault_profiles=(FaultProfile(fault_type, rate=1.0),),
                    )
                )

                self.assertEqual(1.0, result.report.metrics.detection_rate)
                self.assertEqual(1.0, result.report.metrics.recovery_rate)
                self.assertEqual(0, result.report.metrics.unsafe_actions)
                self.assertGreater(len(result.controller_samples), 0)
                self.assertEqual(
                    (),
                    analyze_telemetry(result.controller_samples, expected_samples=result.original_samples),
                )

    def test_recovery_is_driven_by_detected_rules_not_injection_labels(self):
        result = run_scenario(
            ScenarioConfig(
                name="observable recovery",
                samples_per_charger=8,
                fault_profiles=(FaultProfile(FaultType.CONNECTION_DROP, rate=1.0),),
            )
        )

        self.assertTrue(all(not sample.connection_ok for sample in result.observed_samples))
        self.assertTrue(all(sample.connection_ok for sample in result.controller_samples))
        self.assertEqual(result.report.metrics.injected_faults, result.report.metrics.recovered_faults)
        self.assertTrue(all(action.outcome == "passed" for action in result.recovery_actions))

    def test_mixed_scenario_is_repeatable_and_exportable(self):
        config = ScenarioConfig(
            name="Fleet <night> & test",
            seed=27,
            charger_count=2,
            samples_per_charger=25,
            fault_profiles=(
                FaultProfile(FaultType.DELAY, rate=0.15),
                FaultProfile(FaultType.SPIKE, rate=0.1),
                FaultProfile(FaultType.CORRUPT, rate=0.05),
            ),
        )

        first = run_scenario(config)
        second = run_scenario(config)

        self.assertEqual(first, second)
        self.assertGreater(first.report.metrics.injected_faults, 0)
        self.assertEqual(50, first.report.metrics.total_input)
        self.assertEqual(0, first.report.metrics.unsafe_actions)
        self.assertGreater(len(first.recovery_actions), 0)

    def test_html_report_is_offline_and_escapes_scenario_name(self):
        result = run_scenario(ScenarioConfig(name="<script>alert(1)</script>", samples_per_charger=8))

        html = render_html_report(result)

        self.assertIn("Telemetry Fault Lab", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("https://", html)

    def test_html_report_escapes_event_and_recovery_log_content(self):
        result = run_scenario(ScenarioConfig(name="escape audit", samples_per_charger=8))
        malicious = replace(
            result,
            events=(FaultEvent("<img src=x>", 1, FaultType.CORRUPT, "<b>bad</b>"),),
            recovery_actions=(RecoveryAction("<svg>", 1, "<retry>", "passed", "<unsafe>"),),
        )

        html = render_html_report(malicious)

        self.assertIn("&lt;img src=x&gt;", html)
        self.assertIn("&lt;unsafe&gt;", html)
        self.assertNotIn("<img src=x>", html)

    def test_result_json_contains_reproduction_metadata(self):
        result = run_scenario(ScenarioConfig(name="json", seed=9, samples_per_charger=5))
        payload = json.loads(result.to_json())

        self.assertEqual(9, payload["config"]["seed"])
        self.assertIn("metrics", payload)


if __name__ == "__main__":
    unittest.main()
