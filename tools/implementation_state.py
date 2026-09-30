"""Validate checkpoint references and generate a bounded continuation prompt.

Standard library only. Read-only Git inspection; never fetch, execute recorded
commands, mutate a ledger, or infer semantic certification from file continuity.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


DEFAULT_STATE = "docs/implementation/current-state.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
STATES = {"pending", "in_progress", "blocked", "done"}


class StateError(ValueError):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode:
        raise StateError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8")


def commit(root: Path, ref: str) -> str:
    return git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StateError(message)


def text(value: object, label: str) -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{label}: expected nonempty text")


def path_check(value: str) -> None:
    text(value, "path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and ".." not in p.parts and "\\" not in value
            and ":" not in value and not value.startswith("-"), f"unsafe repository path: {value}")


def load(path: Path) -> dict:
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, f"duplicate JSON key: {k}")
            result[k] = v
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def reference_sha(state: dict, reference: dict) -> str:
    return state["checkpoints"][reference["checkpoint"]][reference["source"]]


def validate(root: Path, state: dict) -> None:
    require(state.get("schema") == "SOMA_IMPLEMENTATION_STATE_V1", "unsupported state schema")
    for k in ("repository", "mission", "active_branch", "next_task", "observed_at"):
        text(state.get(k), k)
    require(re.fullmatch(r"[\w.-]+/[\w.-]+", state["repository"]) is not None, "invalid repository")
    checkpoints = state["checkpoints"]
    require("active" in checkpoints and "baseline" in checkpoints, "active/baseline checkpoints required")
    for name, pair in checkpoints.items():
        for source in ("implementation", "design"):
            sha = pair[source]
            require(isinstance(sha, str) and SHA.fullmatch(sha) is not None, f"{name}.{source}: full SHA required")
            require(commit(root, sha) == sha, f"unavailable checkpoint: {name}.{source}")
    for branch, sha in state["observed_heads"].items():
        text(branch, "branch")
        require(isinstance(sha, str) and SHA.fullmatch(sha) is not None, "observed head requires full SHA")
        commit(root, sha)
    require(state["observed_heads"].get(state["active_branch"]) == checkpoints["active"]["implementation"],
            "active checkpoint must match its recorded observed branch head")
    scopes = state["scopes"]
    require(bool(scopes), "at least one scope required")
    for sid, scope in scopes.items():
        require(scope["checkpoint"] in checkpoints, f"{sid}: unknown checkpoint")
        text(scope["summary"], sid)
        for source in ("implementation", "design"):
            require(bool(scope["paths"][source]), f"{sid}: empty {source} scope")
            for pattern in scope["paths"][source]:
                path_check(pattern)
        require(all(d in scopes and d != sid for d in scope["depends_on"]), f"{sid}: invalid dependency")
    def acyclic(items, key):
        visiting, done = set(), set()
        def visit(node):
            require(node not in visiting, f"{key}: dependency cycle at {node}")
            if node in done:
                return
            visiting.add(node)
            for dep in items[node]["depends_on"]:
                visit(dep)
            visiting.remove(node)
            done.add(node)
        for node in items:
            visit(node)
    acyclic(scopes, "scopes")
    for source in ("implementation", "design"):
        for pattern in state["shared_paths"][source] + state["nonsemantic_paths"][source]:
            path_check(pattern)
    evidence = state["evidence"]
    for eid, ref in evidence.items():
        text(ref["purpose"], f"{eid}.purpose")
        require(ref["checkpoint"] in checkpoints, f"{eid}: unknown checkpoint")
        require(ref["source"] in {"implementation", "design"}, f"{eid}: unknown source")
        path_check(ref["path"])
        body = git(root, "show", f"{reference_sha(state, ref)}:{ref['path']}")
        if ref.get("node"):
            # Top-level Python test functions only; no import or execution.
            require(ref["path"].endswith(".py"), f"{eid}: test node requires Python")
            names = {n.name for n in ast.parse(body).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            require(ref["node"] in names, f"{eid}: missing test node {ref['node']}")
    tasks = state["tasks"]
    require(state["next_task"] in tasks, "unknown next_task")
    for tid, task in tasks.items():
        require(task["status"] in STATES, f"{tid}: unknown task status")
        require(task["scope"] in scopes, f"{tid}: unknown scope")
        for field in ("title", "reason", "resume"):
            text(task[field], f"{tid}.{field}")
        for field in ("read_first", "acceptance", "verification"):
            require(isinstance(task[field], list) and bool(task[field]), f"{tid}.{field}: empty")
            for value in task[field]:
                text(value, f"{tid}.{field}")
        require(all(e in evidence for e in task["read_first"]), f"{tid}: unknown evidence")
        require(all(d in tasks and d != tid for d in task["depends_on"]), f"{tid}: invalid dependency")
        if task["status"] == "done":
            require(bool(task.get("completion_evidence")) and all(e in evidence for e in task["completion_evidence"]),
                    f"{tid}: done requires explicit completion evidence")
    acyclic(tasks, "tasks")
    for cid, ci in state["ci"].items():
        text(ci["name"], f"{cid}.name")
        require(ci["checkpoint"] in checkpoints, f"{cid}: unknown checkpoint")
        require(ci["source"] in {"implementation", "design"}, f"{cid}: invalid source")
        require(ci["sha"] == checkpoints[ci["checkpoint"]][ci["source"]], f"{cid}: CI/checkpoint SHA mismatch")
        require(ci["conclusion"] in {"success", "failure", "cancelled", "pending", "unknown"}, f"{cid}: invalid CI result")
        require(type(ci["run_id"]) is int and ci["run_id"] > 0, f"{cid}: invalid run ID")
        text(ci["detail"], f"{cid}.detail")
    for field in ("constraints", "known_limits"):
        require(isinstance(state[field], list) and bool(state[field]), f"{field}: expected list")
        for value in state[field]:
            text(value, field)


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def changed(root: Path, old: str, new: str) -> tuple[list[str], bool]:
    result = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", old, new], capture_output=True)
    require(result.returncode in (0, 1), "cannot establish checkpoint ancestry")
    # Disable rename detection so both removed and added names invalidate scopes.
    names = git(root, "diff", "--no-renames", "--name-only", "-z", old, new, "--")
    return sorted(p for p in names.split("\0") if p), result.returncode == 0


def assess(root: Path, state: dict, implementation_ref: str, design_ref: str) -> dict:
    targets = {"implementation": commit(root, implementation_ref), "design": commit(root, design_ref)}
    diffs, results, unknown = {}, {}, set()
    for sid, scope in state["scopes"].items():
        causes, paths = [], set()
        for source, target in targets.items():
            source_changed = False
            base = state["checkpoints"][scope["checkpoint"]][source]
            key = (base, target)
            if key not in diffs:
                diffs[key] = changed(root, base, target)
            delta, ancestor = diffs[key]
            if not ancestor:
                causes.append(f"{source} checkpoint is not an ancestor; continuity unknown")
            for p in delta:
                direct = matches(p, scope["paths"][source])
                shared = matches(p, state["shared_paths"][source])
                mapped = any(matches(p, s["paths"][source]) for s in state["scopes"].values())
                unclassified = not mapped and not shared and not matches(p, state["nonsemantic_paths"][source])
                if direct or shared or unclassified:
                    paths.add(f"{source}:{p}")
                    source_changed = True
                if unclassified:
                    unknown.add(f"{source}:{p}")
            if source_changed:
                causes.append(f"review affected {source} evidence")
        results[sid] = {"status": "review_required" if causes else "unchanged_in_declared_scope",
                        "reasons": sorted(set(causes)), "changed_paths": sorted(paths)}
    # Conservative fixed-point propagation, including transitive consumers.
    again = True
    while again:
        again = False
        for sid, scope in state["scopes"].items():
            for dep in scope["depends_on"]:
                if results[dep]["status"] == "review_required":
                    reason = f"dependency {dep} requires review"
                    if reason not in results[sid]["reasons"]:
                        results[sid]["reasons"].append(reason)
                        again = True
                    results[sid]["status"] = "review_required"
    dirty = git(root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    return {"targets": targets, "scopes": results, "unclassified_changes": sorted(unknown),
            "working_tree_changes": dirty, "remote_verified": False,
            "note": "Local Git objects only. Unchanged scope is continuity, not semantic certification. Dirty bytes are not audited."}


def render(state: dict, report: dict, task_id: str, manifest_hash: str) -> str:
    require(task_id in state["tasks"], f"unknown task: {task_id}")
    task = state["tasks"][task_id]
    lines = ["# SOMA implementation continuation prompt", "",
             f"You are Nebula (Nebby), implementation collaborator on `{state['repository']}`.",
             state["mission"], "",
             "This is a generated checkpoint, not a live certification or new authorization. Follow the current user's scope and AGENTS.md.",
             "Re-fetch authority heads and CI before mutations. Do not re-audit unchanged packets by default; inspect deltas, affected owners and dependencies. Expand review when mapping is incomplete.",
             "", "## Checkpoint identity", "",
             f"- State observed: {state['observed_at']}; manifest SHA-256: `{manifest_hash}`.",
             f"- Active lane: `{state['active_branch']}`."]
    for name, pair in state["checkpoints"].items():
        lines.append(f"- {name}: implementation `{pair['implementation']}`; design `{pair['design']}`.")
    for branch, sha in state["observed_heads"].items():
        lines.append(f"- Last observed `{branch}`: `{sha}`.")
    lines += ["", "## Freshness check", "", "Remote freshness: NOT checked by this offline tool. Refresh remote refs or use the GitHub connector.",
              f"Compared implementation `{report['targets']['implementation']}` and design `{report['targets']['design']}`."]
    if report["working_tree_changes"]:
        lines.append(f"WARNING: {len(report['working_tree_changes'])} working-tree entries differ; committed-tree analysis excludes those bytes. Preserve and inspect them before editing.")
    for sid, result in report["scopes"].items():
        lines.append(f"- {sid}: **{result['status']}**. {state['scopes'][sid]['summary']}")
        if result["reasons"]:
            lines.append("  Reasons: " + "; ".join(result["reasons"]) + ".")
    paths = sorted({p for r in report["scopes"].values() for p in r["changed_paths"]})
    if paths:
        lines += ["", "Changed paths to inspect (bounded listing):"] + [f"- `{p}`" for p in paths[:30]]
        if len(paths) > 30:
            lines.append(f"- {len(paths)-30} more paths omitted; run `check --json` for the complete list. Do not treat this excerpt as exhaustive.")
    if report["unclassified_changes"]:
        lines.append("Unclassified changes conservatively invalidate scope continuity; extend the mapping only after review.")
    lines += ["", "## Recorded CI evidence", ""]
    for ci in state["ci"].values():
        url = f"https://github.com/{state['repository']}/actions/runs/{ci['run_id']}"
        lines.append(f"- [{ci['name']}]({url}): **{ci['conclusion']}** at `{ci['sha']}`. {ci['detail']}")
    lines += ["", "## Selected task", "", f"**{task_id}: {task['title']}** — recorded status: {task['status']}.",
              task["reason"], "", "Resume from: " + task["resume"]]
    if task["depends_on"]:
        lines.append("Dependencies: " + ", ".join(f"{d} ({state['tasks'][d]['status']})" for d in task["depends_on"]) + ". Do not bypass unfinished prerequisites.")
    lines += ["", "Read first (exact checkpoint sources; fetch current versions if affected):"]
    for eid in task["read_first"]:
        ref = state["evidence"][eid]
        suffix = "::" + ref["node"] if ref.get("node") else ""
        lines.append(f"- `{reference_sha(state, ref)}:{ref['path']}{suffix}` — {ref['purpose']}")
    lines += ["", "Completion criteria:"] + [f"- {c}" for c in task["acceptance"]]
    lines += ["", "Verification to perform (instructions, not claimed results):"] + [f"- {c}" for c in task["verification"]]
    lines += ["", "## Remaining task queue", ""]
    lines += [f"- {tid}: {t['title']} [{t['status']}]" for tid, t in state["tasks"].items() if tid != task_id]
    lines += ["", "## Constraints and known limits", ""] + [f"- {c}" for c in state["constraints"] + state["known_limits"]]
    lines += ["", "## Finish or pause cleanly", "",
              "Update current-state.json at a meaningful checkpoint: exact reviewed SHAs, evidence references, observed CI, task status, next_task and resume details. Preserve historical ledgers; do not copy their entire contents into the manifest.",
              "Pin the inspected source commit, not the commit containing this metadata update: this avoids self-referential SHA churn. A later metadata-only commit does not certify its own code.",
              "Validate state and generate the next prompt with tools/implementation_state.py. Never hand-edit generated prompts or use an old prompt as normative authority.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "check", "prompt"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--implementation-ref", default="HEAD")
    parser.add_argument("--design-ref", help="Explicit refreshed design ref; defaults to recorded active design, never a silent upgrade")
    parser.add_argument("--task")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, help="Prompt destination; default stdout. Existing files are never overwritten.")
    args = parser.parse_args(argv)
    try:
        state_path = args.root / args.state
        state = load(state_path)
        validate(args.root, state)
        if args.command == "validate":
            print("State references valid. No semantic certification or remote verification performed.")
            return 0
        report = assess(args.root, state, args.implementation_ref, args.design_ref or state["checkpoints"]["active"]["design"])
        if args.command == "check":
            print(json.dumps(report, indent=2) if args.json else "\n".join(
                [report["note"], "Remote freshness: NOT checked."] +
                [f"{k}: {v['status']}" for k, v in report["scopes"].items()] +
                [f"Working-tree changes: {len(report['working_tree_changes'])}"]))
            return 2 if report["working_tree_changes"] or any(r["status"] == "review_required" for r in report["scopes"].values()) else 0
        result = render(state, report, args.task or state["next_task"], hashlib.sha256(state_path.read_bytes()).hexdigest())
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(result)
            print(args.output)
        else:
            print(result, end="")
        return 0
    except (StateError, OSError, KeyError, TypeError, SyntaxError, json.JSONDecodeError) as error:
        print(f"State error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
