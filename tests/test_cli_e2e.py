import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliEndToEndTests(unittest.TestCase):
    def test_demo_command_creates_json_csv_and_html_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [sys.executable, "-m", "telemetry_lab", "demo", "--output-dir", temp_dir],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("Detection rate", completed.stdout)
            artifacts = {path.suffix for path in Path(temp_dir).iterdir()}
            self.assertEqual({".csv", ".html", ".json"}, artifacts)
            json_path = next(Path(temp_dir).glob("*.json"))
            self.assertIn("metrics", json.loads(json_path.read_text(encoding="utf-8")))

    def test_invalid_sample_count_returns_actionable_error(self):
        completed = subprocess.run(
            [sys.executable, "-m", "telemetry_lab", "run", "--samples", "0"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("samples", completed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
