#!/usr/bin/env python3
"""Deterministically validate the RC-006-A2 B002 input manifest.

This validator is intentionally pinned to A2-BASELINE-002. It accepts no
command-line override for the source commit/tree or frozen manifest identities.
It requires a Git clone that contains the referenced objects and uses only the
Python standard library plus the local Git executable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

VALIDATOR_VERSION = "1.0.0"

SOURCE_COMMIT = "61bbd665535e942ef3b05c5ed45661639d3a37a9"
SOURCE_TREE = "b6f7fcddd8723f0ba231bb8b9f8ca49be8a6eec8"
MANIFEST_REF = "221bfdbbbb660387c407c44ac6e119a749c0dfbd"
MANIFEST_PATH = "docs/reconciliation/RC006_A2_INPUT_MANIFEST.tsv"
MANIFEST_BLOB_SHA = "05daa81310b8259ca8ff968bd1715244ecf0d5d5"
MANIFEST_PAYLOAD_SHA256 = (
    "3bbe5c2f6c82b4ddaf4ecbc2825ace3b0edc3072e67fe09f6e68447e89fd1013"
)
EXPECTED_FILE_COUNT = 92
EXPECTED_INCLUDED_COUNT = 74
EXPECTED_EXCLUDED_COUNT = 18
MANIFEST_MAGIC = "A2-CORPUS-MANIFEST-V1"
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(RuntimeError):
    """Raised when execution cannot proceed far enough to produce a result."""


def _git(repo: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ValidationError("git executable not found") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise ValidationError(f"git {' '.join(args)} failed: {stderr}") from exc
    return completed.stdout


def _validator_identity() -> tuple[str, str]:
    source = Path(__file__).resolve().read_bytes()
    sha256 = hashlib.sha256(source).hexdigest()
    header = f"blob {len(source)}\0".encode("ascii")
    git_blob_sha = hashlib.sha1(header + source).hexdigest()
    return git_blob_sha, sha256


def _parse_tree(repo: Path) -> tuple[dict[str, str], int]:
    raw = _git(repo, "ls-tree", "-r", "-z", SOURCE_TREE)
    blobs: dict[str, str] = {}
    non_blob_leaf_count = 0
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode, obj_type, obj_sha = metadata.decode("ascii").split(" ", 2)
            del mode
            path = path_bytes.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError("malformed or non-UTF-8 git ls-tree record") from exc
        if obj_type != "blob":
            non_blob_leaf_count += 1
            continue
        if path in blobs:
            raise ValidationError(f"duplicate path emitted by git ls-tree: {path}")
        blobs[path] = obj_sha
    return blobs, non_blob_leaf_count


def _parse_manifest(manifest: bytes) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    format_errors: list[str] = []
    metadata: dict[str, Any] = {}
    records: dict[str, str] = {}

    metadata["manifest_has_final_lf"] = manifest.endswith(b"\n")
    metadata["manifest_cr_count"] = manifest.count(b"\r")
    if not metadata["manifest_has_final_lf"]:
        format_errors.append("manifest_missing_final_lf")
    if metadata["manifest_cr_count"] != 0:
        format_errors.append("manifest_contains_cr")

    first_lf = manifest.find(b"\n")
    if first_lf < 0:
        raise ValidationError("manifest has no LF delimiter")
    digest_line = manifest[:first_lf]
    payload = manifest[first_lf + 1 :]

    try:
        digest_text = digest_line.decode("ascii")
        digest_fields = digest_text.split("\t")
    except UnicodeDecodeError as exc:
        raise ValidationError("manifest digest line is not ASCII") from exc

    declared_digest = ""
    if len(digest_fields) != 2 or digest_fields[0] != "manifest_sha256":
        format_errors.append("malformed_manifest_digest_line")
    else:
        declared_digest = digest_fields[1]
        if not _SHA256_RE.fullmatch(declared_digest):
            format_errors.append("malformed_manifest_declared_sha256")

    computed_digest = hashlib.sha256(payload).hexdigest()
    metadata["manifest_declared_payload_sha256"] = declared_digest
    metadata["manifest_computed_payload_sha256"] = computed_digest

    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("manifest payload is not valid UTF-8") from exc

    lines = text.splitlines()
    if len(lines) < 6:
        raise ValidationError("manifest payload is too short")
    if lines[0] != MANIFEST_MAGIC:
        format_errors.append("manifest_magic_mismatch")

    expected_meta_keys = [
        "source_commit",
        "source_tree",
        "file_count",
        "included_count",
        "excluded_count",
    ]
    parsed_meta: dict[str, str] = {}
    for index, key in enumerate(expected_meta_keys, start=1):
        fields = lines[index].split("\t")
        if len(fields) != 2 or fields[0] != key:
            format_errors.append(f"malformed_metadata_{key}")
            continue
        parsed_meta[key] = fields[1]

    malformed_row_count = 0
    empty_reason_count = 0
    invalid_sha_count = 0
    invalid_class_count = 0
    duplicate_path_count = 0
    path_order: list[str] = []
    include_count = 0
    exclude_count = 0

    for line in lines[6:]:
        fields = line.split("\t")
        if len(fields) != 4:
            malformed_row_count += 1
            continue
        classification, path, blob_sha, reason = fields
        if classification not in {"INCLUDE", "EXCLUDE"}:
            invalid_class_count += 1
        if not path:
            malformed_row_count += 1
            continue
        if not _SHA1_RE.fullmatch(blob_sha):
            invalid_sha_count += 1
        if not reason:
            empty_reason_count += 1
        if path in records:
            duplicate_path_count += 1
        else:
            records[path] = blob_sha
            path_order.append(path)
        if classification == "INCLUDE":
            include_count += 1
        elif classification == "EXCLUDE":
            exclude_count += 1

    bytewise_sorted = sorted(path_order, key=lambda value: value.encode("utf-8"))
    metadata.update(
        {
            "manifest_record_count": len(lines[6:]),
            "manifest_unique_path_count": len(records),
            "manifest_include_count": include_count,
            "manifest_exclude_count": exclude_count,
            "manifest_malformed_row_count": malformed_row_count,
            "manifest_empty_reason_count": empty_reason_count,
            "manifest_invalid_sha_count": invalid_sha_count,
            "manifest_invalid_class_count": invalid_class_count,
            "manifest_duplicate_path_count": duplicate_path_count,
            "manifest_path_order_mismatch_count": 0 if path_order == bytewise_sorted else 1,
            "parsed_metadata": parsed_meta,
        }
    )
    return metadata, records, format_errors


def validate(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    top = Path(_git(repo, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()

    resolved_source_tree = _git(top, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}").decode("ascii").strip()
    manifest_blob = _git(top, "rev-parse", f"{MANIFEST_REF}:{MANIFEST_PATH}").decode("ascii").strip()
    manifest = _git(top, "show", f"{MANIFEST_REF}:{MANIFEST_PATH}")
    tree_blobs, non_blob_leaf_count = _parse_tree(top)
    parsed, manifest_records, format_errors = _parse_manifest(manifest)
    validator_blob_sha, validator_sha256 = _validator_identity()

    tree_paths = set(tree_blobs)
    manifest_paths = set(manifest_records)
    missing_paths = sorted(tree_paths - manifest_paths, key=lambda value: value.encode("utf-8"))
    extra_paths = sorted(manifest_paths - tree_paths, key=lambda value: value.encode("utf-8"))
    blob_mismatches = sorted(
        [
            path
            for path in tree_paths & manifest_paths
            if tree_blobs[path] != manifest_records[path]
        ],
        key=lambda value: value.encode("utf-8"),
    )

    parsed_meta = parsed["parsed_metadata"]
    checks = {
        "source_commit_resolves_to_expected_tree": resolved_source_tree == SOURCE_TREE,
        "manifest_blob_sha_matches": manifest_blob == MANIFEST_BLOB_SHA,
        "manifest_declared_payload_sha256_matches_expected": parsed[
            "manifest_declared_payload_sha256"
        ]
        == MANIFEST_PAYLOAD_SHA256,
        "manifest_recomputed_payload_sha256_matches_expected": parsed[
            "manifest_computed_payload_sha256"
        ]
        == MANIFEST_PAYLOAD_SHA256,
        "manifest_format_errors_zero": len(format_errors) == 0,
        "manifest_has_final_lf": parsed["manifest_has_final_lf"],
        "manifest_cr_count_zero": parsed["manifest_cr_count"] == 0,
        "manifest_malformed_rows_zero": parsed["manifest_malformed_row_count"] == 0,
        "manifest_empty_reasons_zero": parsed["manifest_empty_reason_count"] == 0,
        "manifest_invalid_sha_zero": parsed["manifest_invalid_sha_count"] == 0,
        "manifest_invalid_class_zero": parsed["manifest_invalid_class_count"] == 0,
        "manifest_duplicate_paths_zero": parsed["manifest_duplicate_path_count"] == 0,
        "manifest_path_order_bytewise_utf8": parsed["manifest_path_order_mismatch_count"] == 0,
        "manifest_metadata_source_commit_matches": parsed_meta.get("source_commit") == SOURCE_COMMIT,
        "manifest_metadata_source_tree_matches": parsed_meta.get("source_tree") == SOURCE_TREE,
        "manifest_metadata_file_count_matches": parsed_meta.get("file_count")
        == str(EXPECTED_FILE_COUNT),
        "manifest_metadata_included_count_matches": parsed_meta.get("included_count")
        == str(EXPECTED_INCLUDED_COUNT),
        "manifest_metadata_excluded_count_matches": parsed_meta.get("excluded_count")
        == str(EXPECTED_EXCLUDED_COUNT),
        "source_tree_blob_count_matches": len(tree_blobs) == EXPECTED_FILE_COUNT,
        "source_tree_non_blob_leaves_zero": non_blob_leaf_count == 0,
        "manifest_record_count_matches": parsed["manifest_record_count"] == EXPECTED_FILE_COUNT,
        "manifest_unique_path_count_matches": parsed["manifest_unique_path_count"]
        == EXPECTED_FILE_COUNT,
        "manifest_include_count_matches": parsed["manifest_include_count"]
        == EXPECTED_INCLUDED_COUNT,
        "manifest_exclude_count_matches": parsed["manifest_exclude_count"]
        == EXPECTED_EXCLUDED_COUNT,
        "missing_paths_zero": len(missing_paths) == 0,
        "extra_paths_zero": len(extra_paths) == 0,
        "blob_sha_mismatches_zero": len(blob_mismatches) == 0,
    }

    passed = all(checks.values())
    result: dict[str, Any] = {
        "schema": "RC006-A2-MANIFEST-VALIDATION-RESULT-V1",
        "validator_version": VALIDATOR_VERSION,
        "validator_git_blob_sha": validator_blob_sha,
        "validator_sha256": validator_sha256,
        "source_commit": SOURCE_COMMIT,
        "expected_source_tree": SOURCE_TREE,
        "resolved_source_tree": resolved_source_tree,
        "manifest_ref": MANIFEST_REF,
        "manifest_path": MANIFEST_PATH,
        "expected_manifest_blob_sha": MANIFEST_BLOB_SHA,
        "resolved_manifest_blob_sha": manifest_blob,
        "expected_manifest_payload_sha256": MANIFEST_PAYLOAD_SHA256,
        "computed_manifest_payload_sha256": parsed["manifest_computed_payload_sha256"],
        "counts": {
            "source_tree_blobs": len(tree_blobs),
            "source_tree_non_blob_leaves": non_blob_leaf_count,
            "manifest_records": parsed["manifest_record_count"],
            "manifest_unique_paths": parsed["manifest_unique_path_count"],
            "manifest_included": parsed["manifest_include_count"],
            "manifest_excluded": parsed["manifest_exclude_count"],
            "manifest_format_errors": len(format_errors),
            "manifest_malformed_rows": parsed["manifest_malformed_row_count"],
            "manifest_empty_reasons": parsed["manifest_empty_reason_count"],
            "manifest_invalid_shas": parsed["manifest_invalid_sha_count"],
            "manifest_invalid_classes": parsed["manifest_invalid_class_count"],
            "manifest_duplicate_paths": parsed["manifest_duplicate_path_count"],
            "manifest_path_order_mismatches": parsed["manifest_path_order_mismatch_count"],
            "missing_paths": len(missing_paths),
            "extra_paths": len(extra_paths),
            "blob_sha_mismatches": len(blob_mismatches),
        },
        "checks": checks,
        "format_errors": format_errors,
        "missing_paths": missing_paths,
        "extra_paths": extra_paths,
        "blob_sha_mismatch_paths": blob_mismatches,
        "result": "PASS" if passed else "FAIL",
    }
    return result


def _canonical_result_bytes(result: dict[str, Any]) -> bytes:
    return (
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=".",
        help="Path inside a Git clone containing the pinned B002 objects (default: .)",
    )
    parser.add_argument(
        "--output",
        help="Optional path for deterministic validation output; existing files are replaced",
    )
    parser.add_argument("--version", action="store_true", help="Print validator version and exit")
    args = parser.parse_args()

    if args.version:
        print(VALIDATOR_VERSION)
        return 0

    try:
        result = validate(Path(args.repo))
    except ValidationError as exc:
        print(f"VALIDATOR_EXECUTION_ERROR\t{exc}", file=sys.stderr)
        return 2

    payload = _canonical_result_bytes(result)
    result_sha256 = hashlib.sha256(payload).hexdigest()
    rendered = f"result_sha256\t{result_sha256}\n".encode("ascii") + payload

    if args.output:
        Path(args.output).write_bytes(rendered)
    sys.stdout.buffer.write(rendered)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
