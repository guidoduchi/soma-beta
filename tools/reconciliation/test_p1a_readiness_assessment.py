"""Checkpoint-specific identity accounting tests; no semantic PASS is inferred."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("readiness", Path(__file__).with_name("check_p1a_readiness_assessment.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
REPO = Path(__file__).resolve().parents[2]


class ReadinessAssessmentTests(unittest.TestCase):
    def test_checkpoint_accounting(self):
        result = audit.check(REPO)
        self.assertEqual(result["assessment_rows"], 95)
        self.assertEqual(result["states"], {"A": 1, "P": 1, "S": 92, "R": 1})
        self.assertEqual(result["seeds_without_main_flow"], [f"UC-{n:03d}" for n in range(85, 91)])

    def reject_report_change(self, old, new):
        original = Path.read_text

        def read(path, *args, **kwargs):
            content = original(path, *args, **kwargs)
            return content.replace(old, new) if path.name == Path(audit.ASSESSMENT).name else content

        with patch.object(Path, "read_text", read):
            with self.assertRaises(ValueError):
                audit.check(REPO)

    def test_missing_row_rejected(self):
        self.reject_report_change("| UC-095 | W7 | S |", "| omitted | W7 | S |")

    def test_false_acceptance_rejected(self):
        self.reject_report_change("| UC-002 | W1 | P |", "| UC-002 | W1 | A |")

    def test_duplicate_identity_rejected(self):
        self.reject_report_change("| UC-095 | W7 | S |", "| UC-094 | W7 | S |")


if __name__ == "__main__":
    unittest.main()
