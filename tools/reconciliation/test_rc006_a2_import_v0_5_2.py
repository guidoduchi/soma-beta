"""Nonmutating regression tests; synthetic records are never allocation inputs."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("import_v052", Path(__file__).with_name("prepare_rc006_a2_import_candidates_v0_5_2.py"))
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def fixture():
    rows = [{"section_ordinal": section, "review_note": "unchanged"}
            for section in generator.EXPECTED_SECTIONS if section != 26]
    rows += [{"section_ordinal": 1, "review_note": "unchanged"} for _ in range(163)]
    for ordinal, line, kind, text in [(1, 256, "PERMISSION", "The format may represent test facts."),
                                     (2, 258, "PROHIBITION", generator.TARGET_TEXT)]:
        rows.append({"section_ordinal": 26, "assertion_ordinal": ordinal,
                     "source_start_line": line, "source_end_line": line,
                     "normative_kind": kind, "exact_text": text, "review_note": "old note",
                     "source_path": generator.SOURCE_PATH, "source_blob_sha": generator.SOURCE_BLOB,
                     "section_heading": "9.2 Allowed capability boundary",
                     "section_anchor": "92-allowed-capability-boundary", "fingerprint_sha256": "unchanged"})
    return rows


class ReferentReviewTests(unittest.TestCase):
    def test_only_target_note_changes_and_input_remains_untouched(self):
        rows = fixture()
        before = copy.deepcopy(rows)
        after = generator.annotate(rows)
        self.assertEqual(rows, before)
        self.assertEqual(len(after), 186)
        self.assertEqual(after[-1]["review_note"], generator.REVIEW_NOTE)
        after[-1]["review_note"] = before[-1]["review_note"]
        self.assertEqual(after, before)

    def test_refuse_185_merge(self):
        with self.assertRaisesRegex(ValueError, "count"):
            generator.annotate(fixture()[:-1])

    def test_refuse_extra_candidate(self):
        with self.assertRaisesRegex(ValueError, "count"):
            generator.annotate(fixture() + [fixture()[0]])

    def test_refuse_section_substitution(self):
        rows = fixture()
        rows[0]["section_ordinal"] = 999
        with self.assertRaisesRegex(ValueError, "section set"):
            generator.annotate(rows)

    def test_refuse_target_identity_changes(self):
        for field in ["assertion_ordinal", "source_start_line", "source_end_line", "source_path",
                      "source_blob_sha", "normative_kind", "section_heading", "section_anchor"]:
            with self.subTest(field=field):
                rows = fixture()
                rows[-1][field] = "wrong"
                with self.assertRaisesRegex(ValueError, "identity or boundary"):
                    generator.annotate(rows)

    def test_refuse_text_rewrite(self):
        rows = fixture()
        rows[-1]["exact_text"] = "The workbook contains no password."
        with self.assertRaisesRegex(ValueError, "exact text"):
            generator.annotate(rows)

    def test_refuse_wrong_antecedent(self):
        rows = fixture()
        rows[-2]["exact_text"] = "Something else."
        with self.assertRaisesRegex(ValueError, "exact text"):
            generator.annotate(rows)

    def test_refuse_extra_target(self):
        rows = fixture()
        rows[30] = copy.deepcopy(rows[-1])
        with self.assertRaisesRegex(ValueError, "two separate"):
            generator.annotate(rows)

    def test_refuse_stable_ids(self):
        rows = fixture()
        rows[0]["assertion_id"] = "A2-ASSERT-000432"
        with self.assertRaisesRegex(ValueError, "stable assertion"):
            generator.annotate(rows)

    def test_payload_identity_checked_before_parse(self):
        with self.assertRaisesRegex(ValueError, "payload identity"):
            generator.transform(b"not JSON")

    def test_same_count_substitution_rejected(self):
        payload = b"".join(generator.encode(row) for row in fixture())
        with self.assertRaisesRegex(ValueError, "payload identity"):
            generator.transform(payload)

    def test_transform_uses_validated_bytes(self):
        payload = b"".join(generator.encode(row) for row in fixture())
        with patch.object(generator, "PARENT_PAYLOAD", generator.digest(payload)):
            result = generator.transform(payload)
        self.assertEqual(result[-1]["review_note"], generator.REVIEW_NOTE)

    def test_repeated_annotation_is_not_a_new_correction(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            generator.annotate(generator.annotate(fixture()))

    def test_output_cannot_overwrite_repository(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                generator.review_output_paths(repo, [str(repo / "allocation-state.json")])

    def test_output_aliases_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            with self.assertRaisesRegex(ValueError, "distinct"):
                generator.review_output_paths(repo, [str(Path(td) / "review"), str(Path(td) / "review")])

    def test_output_symlink_into_repository_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            link = Path(td) / "alias"
            link.symlink_to(repo, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                generator.review_output_paths(repo, [str(link / "ledger")])


if __name__ == "__main__":
    unittest.main()
