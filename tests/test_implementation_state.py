"""Real disposable Git histories prove conservative continuation behavior."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "tools" / "implementation_state.py"
SPEC = importlib.util.spec_from_file_location("implementation_state", TOOL)
state_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state_tool)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "State Test")
        self.git("config", "commit.gpgsign", "false")
        self.write("src/provider.py", "VALUE = 1\n")
        self.write("src/consumer.py", "VALUE = 1\n")
        self.write("tests/test_owner.py", "def test_exact():\n    pass\n")
        self.write("spec/provider.json", "{}\n")
        self.base = self.save("baseline")
        self.state = {
            "schema": "SOMA_IMPLEMENTATION_STATE_V1", "repository": "owner/repo",
            "observed_at": "2026-09-29T00:00:00Z", "mission": "Continue bounded work.",
            "active_branch": "work", "next_task": "fix",
            "checkpoints": {k: {"implementation": self.base, "design": self.base} for k in ("active", "baseline")},
            "observed_heads": {"work": self.base},
            "shared_paths": {"implementation": ["src/foundation/*"], "design": ["spec/global/*"]},
            "nonsemantic_paths": {"implementation": ["docs/*"], "design": ["docs/*"]},
            "scopes": {
                "provider": {"checkpoint": "active", "paths": {"implementation": ["src/provider.py", "tests/*", "docs/proof.json"], "design": ["spec/provider.json"]}, "depends_on": [], "summary": "Provider evidence."},
                "consumer": {"checkpoint": "active", "paths": {"implementation": ["src/consumer.py"], "design": ["spec/consumer.json"]}, "depends_on": ["provider"], "summary": "Consumer evidence."},
            },
            "evidence": {"test": {"checkpoint": "active", "source": "implementation", "path": "tests/test_owner.py", "node": "test_exact", "purpose": "Exact regression."}},
            "ci": {"test": {"name": "CI #1", "checkpoint": "active", "source": "implementation", "sha": self.base, "run_id": 1, "conclusion": "failure", "detail": "Failure remains open."}},
            "tasks": {"fix": {"title": "Repair owner", "status": "pending", "scope": "provider", "depends_on": [], "reason": "Observed failure.", "resume": "Inspect exact failure.", "read_first": ["test"], "acceptance": ["Prove contract."], "verification": ["Run exact test."]}},
            "constraints": ["Never invent authority."], "known_limits": ["No live CI lookup."],
        }

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def write(self, path, body):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    def save(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def assess(self, design=None):
        return state_tool.assess(self.root, self.state, "HEAD", design or self.base)

    def test_clean_checkpoint_has_no_remote_or_semantic_certification(self):
        state_tool.validate(self.root, self.state)
        report = self.assess()
        self.assertFalse(report["remote_verified"])
        self.assertEqual(report["scopes"]["provider"]["status"], "unchanged_in_declared_scope")

    def test_provider_edit_invalidates_transitive_consumer(self):
        self.write("src/provider.py", "VALUE = 2\n")
        self.save("change")
        report = self.assess()
        self.assertEqual(report["scopes"]["provider"]["status"], "review_required")
        self.assertIn("dependency provider requires review", report["scopes"]["consumer"]["reasons"])

    def test_consumer_edit_does_not_invalidate_provider(self):
        self.write("src/consumer.py", "VALUE = 2\n")
        self.save("consumer")
        self.assertEqual(self.assess()["scopes"]["provider"]["status"], "unchanged_in_declared_scope")

    def test_new_unmapped_source_invalidates_all(self):
        self.write("src/new_owner.py", "VALUE = 1\n")
        self.save("unknown")
        report = self.assess()
        self.assertEqual(report["unclassified_changes"], ["implementation:src/new_owner.py"])
        self.assertTrue(all(s["status"] == "review_required" for s in report["scopes"].values()))

    def test_shared_foundation_change_invalidates_all(self):
        self.write("src/foundation/uow.py", "VALUE = 1\n")
        self.save("shared")
        self.assertTrue(all(s["status"] == "review_required" for s in self.assess()["scopes"].values()))

    def test_documentation_only_continuity_but_scoped_ledger_invalidates(self):
        self.write("docs/note.md", "historical\n")
        self.save("docs")
        self.assertEqual(self.assess()["scopes"]["provider"]["status"], "unchanged_in_declared_scope")
        self.write("docs/proof.json", "{}\n")
        self.save("proof")
        self.assertEqual(self.assess()["scopes"]["provider"]["status"], "review_required")

    def test_rename_retains_deleted_scope_invalidation(self):
        (self.root / "docs").mkdir()
        self.git("mv", "src/provider.py", "docs/provider.txt")
        self.save("rename")
        self.assertIn("implementation:src/provider.py", self.assess()["scopes"]["provider"]["changed_paths"])

    def test_design_change_is_detected_without_silent_pin_upgrade(self):
        self.write("spec/provider.json", '{"changed": true}\n')
        new = self.save("design")
        report = state_tool.assess(self.root, self.state, self.base, new)
        self.assertIn("design:spec/provider.json", report["scopes"]["provider"]["changed_paths"])
        self.assertEqual(self.state["checkpoints"]["active"]["design"], self.base)

    def test_nonancestor_with_identical_tree_cannot_claim_continuity(self):
        self.git("commit", "--allow-empty", "-qm", "later")
        later = self.git("rev-parse", "HEAD")
        self.state["checkpoints"]["active"]["implementation"] = later
        report = state_tool.assess(self.root, self.state, self.base, self.base)
        self.assertEqual(report["scopes"]["provider"]["status"], "review_required")

    def test_dirty_and_untracked_bytes_are_explicit(self):
        self.write("src/provider.py", "dirty\n")
        self.write("notes.txt", "untracked\n")
        report = self.assess()
        self.assertEqual(len(report["working_tree_changes"]), 2)
        prompt = state_tool.render(self.state, report, "fix", "abc")
        self.assertIn("committed-tree analysis excludes those bytes", prompt)

    def test_validation_rejects_missing_file_test_node_and_ci_sha_mismatch(self):
        for mutate in (
            lambda s: s["evidence"]["test"].update(path="tests/missing.py"),
            lambda s: s["evidence"]["test"].update(node="test_missing"),
            lambda s: s["ci"]["test"].update(sha="0" * 40),
            lambda s: s["evidence"]["test"].update(path="../escape.py"),
            lambda s: s["checkpoints"]["active"].update(design="f" * 40),
        ):
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(self.state)
                mutate(candidate)
                with self.assertRaises(state_tool.StateError):
                    state_tool.validate(self.root, candidate)

    def test_dependency_cycles_and_done_without_evidence_fail_closed(self):
        self.state["scopes"]["provider"]["depends_on"] = ["consumer"]
        with self.assertRaisesRegex(state_tool.StateError, "cycle"):
            state_tool.validate(self.root, self.state)
        self.state["scopes"]["provider"]["depends_on"] = []
        self.state["tasks"]["fix"]["status"] = "done"
        with self.assertRaisesRegex(state_tool.StateError, "completion evidence"):
            state_tool.validate(self.root, self.state)

    def test_duplicate_json_keys_rejected(self):
        self.write("state.json", '{"schema": "one", "schema": "two"}')
        with self.assertRaisesRegex(state_tool.StateError, "duplicate"):
            state_tool.load(self.root / "state.json")

    def test_prompt_is_deterministic_and_carries_action_evidence_and_limits(self):
        report = self.assess()
        prompt = state_tool.render(self.state, report, "fix", "abc")
        self.assertEqual(prompt, state_tool.render(self.state, report, "fix", "abc"))
        for expected in ("You are Nebula", "**failure**", "test_exact", "Repair owner", "Completion criteria", "No live CI lookup", "NOT checked", "Finish or pause cleanly"):
            self.assertIn(expected, prompt)

    def test_prompt_truncation_is_explicit(self):
        for i in range(35):
            self.write(f"src/new{i}.py", "VALUE = 1\n")
        self.save("many")
        prompt = state_tool.render(self.state, self.assess(), "fix", "abc")
        self.assertIn("5 more paths omitted", prompt)
        self.assertIn("check --json", prompt)

    def test_cli_check_exit_codes_and_output_refuses_overwrite(self):
        self.write("docs/state.json", json.dumps(self.state))
        self.save("state")
        def cli(*args):
            import sys
            return subprocess.run([sys.executable, str(TOOL), *args, "--root", str(self.root), "--state", "docs/state.json"], capture_output=True, text=True)
        self.assertEqual(cli("check").returncode, 0)
        out = self.root / "prompt.md"
        self.assertEqual(cli("prompt", "--output", str(out)).returncode, 0)
        content = out.read_bytes()
        self.assertEqual(cli("prompt", "--output", str(out)).returncode, 1)
        self.assertEqual(out.read_bytes(), content)
        self.assertEqual(cli("check").returncode, 2)
        self.assertEqual(cli("prompt", "--task", "missing").returncode, 1)


if __name__ == "__main__":
    unittest.main()
