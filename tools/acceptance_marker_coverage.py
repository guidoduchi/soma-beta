from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import tokenize
from pathlib import Path
from typing import Callable

_PACKET_SPECS = {
    "LLD01": "foundation-runtime",
    "LLD02": "identity-reference",
    "LLD03": "tickets-core",
    "LLD04": "rfc-wfm-import",
    "LLD05": "objectives-tasks",
    "LLD06": "product-line-sla",
    "LLD07": "inventory",
}

_TEST_MATCHERS: dict[str, Callable[[str], bool]] = {
    "LLD01": lambda name: name.startswith("test_foundation_"),
    "LLD02": lambda name: name.startswith("test_reference_"),
    "LLD03": lambda name: (
        name.startswith("test_ticket_")
        or name.startswith("test_tickets_")
        or name.startswith("test_sr_reference_")
    ) and not name.startswith("test_ticket_import_"),
    "LLD04": lambda name: name.startswith("test_ticket_import_"),
    "LLD05": lambda name: name.startswith("test_objectives_tasks_"),
    "LLD06": lambda name: name.startswith("test_product_line_sla_"),
    "LLD07": lambda name: name.startswith("test_inventory_"),
}


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        text=True,
        encoding="utf-8",
        errors="strict",
    )


def _design_test_paths(design_ref: str, packet_dir: str) -> tuple[str, ...]:
    prefix = f"spec/lld/{packet_dir}/tests"
    output = _git("ls-tree", "-r", "--name-only", design_ref, prefix)
    return tuple(
        line
        for line in output.splitlines()
        if line.endswith(".json") and line.startswith(prefix + "/")
    )


def _design_text(design_ref: str, path: str) -> str:
    return _git("show", f"{design_ref}:{path}")


def _test_functions(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(1)
        for match in re.finditer(
            r"^def\s+(test_[A-Za-z0-9_]+)\s*\(",
            text,
            flags=re.MULTILINE,
        )
    )


def _without_comments(text: str) -> str:
    try:
        tokens = []
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                token = tokenize.TokenInfo(
                    token.type,
                    "",
                    token.start,
                    token.end,
                    token.line,
                )
            tokens.append(token)
        return tokenize.untokenize(tokens)
    except (IndentationError, tokenize.TokenError):
        return text


def _test_function_sources(text: str) -> tuple[tuple[str, str], ...]:
    lines = text.splitlines(keepends=True)
    starts = [
        (match.group(1), text.count("\n", 0, match.start()) + 1)
        for match in re.finditer(
            r"^def\s+(test_[A-Za-z0-9_]+)\s*\(",
            text,
            flags=re.MULTILINE,
        )
    ]
    if not starts:
        return ()
    output: list[tuple[str, str]] = []
    for index, (name, start_line) in enumerate(starts):
        end_line = (
            starts[index + 1][1] - 1
            if index + 1 < len(starts)
            else len(lines)
        )
        segment = "".join(lines[start_line - 1 : end_line])
        output.append((name, _without_comments(segment)))
    return tuple(output)


def _markers_for_packet(
    *,
    repo_root: Path,
    packet: str,
    packet_dir: str,
    design_ref: str,
) -> dict[str, object]:
    full_id = re.compile(rf"{packet}-T\d{{3}}")
    normative: set[str] = set()
    for path in _design_test_paths(design_ref, packet_dir):
        normative.update(full_id.findall(_design_text(design_ref, path)))

    evidence: dict[str, set[str]] = {}
    matcher = _TEST_MATCHERS[packet]
    for path in sorted((repo_root / "tests").glob("test_*.py")):
        if not matcher(path.name):
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(repo_root).as_posix()

        for function_name, function_source in _test_function_sources(text):
            for marker in full_id.findall(function_source):
                evidence.setdefault(marker, set()).add(
                    f"{relative}::{function_name}::<explicit-reference>"
                )
            for match in re.finditer(r"(?:^|_)t(\d{3})(?=_|$)", function_name):
                marker = f"{packet}-T{match.group(1)}"
                evidence.setdefault(marker, set()).add(
                    f"{relative}::{function_name}"
                )
            for match in re.finditer(
                rf"{packet.lower()}_t(\d{{3}})",
                function_name,
            ):
                marker = f"{packet}-T{match.group(1)}"
                evidence.setdefault(marker, set()).add(
                    f"{relative}::{function_name}"
                )

    normative_ids = tuple(sorted(normative))
    direct_ids = tuple(
        marker for marker in normative_ids if evidence.get(marker)
    )
    missing_ids = tuple(
        marker for marker in normative_ids if not evidence.get(marker)
    )
    return {
        "normative_ids": normative_ids,
        "normative_count": len(normative_ids),
        "direct_marker_count": len(direct_ids),
        "missing_direct_markers": missing_ids,
        "direct_evidence": {
            marker: sorted(evidence[marker])
            for marker in direct_ids
        },
        "semantic_certification": "NOT_PERFORMED",
    }


def build_coverage(repo_root: Path, design_ref: str) -> dict[str, object]:
    resolved_design_sha = _git("rev-parse", design_ref).strip()
    implementation_sha = _git("rev-parse", "HEAD").strip()
    packets = {
        packet: _markers_for_packet(
            repo_root=repo_root,
            packet=packet,
            packet_dir=packet_dir,
            design_ref=design_ref,
        )
        for packet, packet_dir in _PACKET_SPECS.items()
    }
    return {
        "schema": "SOMA_PRE_LLD08_ACCEPTANCE_MARKER_COVERAGE_V2",
        "design_sha": resolved_design_sha,
        "implementation_sha": implementation_sha,
        "interpretation": (
            "Direct markers are a mechanical traceability aid only and comments "
            "do not count as evidence. Marker presence is not semantic certification. "
            "A missing marker requires manual proof binding; it does not by itself "
            "mean the acceptance behavior is unimplemented or untested."
        ),
        "packets": packets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design-ref", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--enforce-direct-markers",
        action="store_true",
        help="return nonzero when any normative test ID lacks a direct test-function marker",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    coverage = build_coverage(repo_root, args.design_ref)
    rendered = json.dumps(
        coverage,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    if args.json:
        print("SOMA_ACCEPTANCE_MARKER_COVERAGE_BEGIN")
        print(rendered)
        print("SOMA_ACCEPTANCE_MARKER_COVERAGE_END")
    else:
        for packet, detail in coverage["packets"].items():
            print(
                f"{packet}: {detail['direct_marker_count']}/"
                f"{detail['normative_count']} direct markers; "
                f"{len(detail['missing_direct_markers'])} require manual binding"
            )
    if args.enforce_direct_markers and any(
        detail["missing_direct_markers"]
        for detail in coverage["packets"].values()
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
