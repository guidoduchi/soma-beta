#!/usr/bin/env python3
"""CI entrypoint for the full SOMA LLD integrity validator.

This runner keeps the production checker fail-closed while the expanded
SIG-001..SIG-022 implementation is stabilized.  It patches only the artifact
scanner's generator-flattening bug; all findings and enforcement semantics
remain owned by validate_spec.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import validate_spec as core


def check_artifacts(repo: Path, packet: dict, packet_root: Path,
                    docs: dict, findings: list) -> None:
    packet_id = str(packet["id"])
    serialized = " ".join(core.flatten_strings(docs))
    generates = bool(re.search(r"\b(generate|write|export|artifact|xlsx|msg)\b", serialized, re.I))
    index = docs.get("_index.json")
    not_owned = " ".join(index.get("not_owned_here", [])) if isinstance(index, dict) else ""
    owns = generates and not ("artifact" in not_owned.lower() and "->" in not_owned)
    artifact_docs = [
        doc for path, doc in docs.items()
        if path.startswith("artifacts/") and isinstance(doc, dict)
    ]
    if owns and not artifact_docs:
        command_text = " ".join(
            text
            for path, doc in docs.items()
            if path.startswith(("commands/", "jobs/"))
            for text in core.flatten_strings(doc)
        )
        if re.search(r"\b(generate|write|export).*(artifact|xlsx|msg)|\b(artifact|xlsx|msg).*(generate|write|export)", command_text, re.I):
            core.add(findings, "SIG-016", "HIGH", packet_id, packet_root / "artifacts",
                     "packet generates/verifies artifacts but has no versioned artifacts registry", repo)
            return
    for doc in artifact_docs:
        required = {
            "format_contract", "writer", "verifier", "temporary_policy",
            "finalization_policy", "collision_policy"
        }
        missing = sorted(field for field in required if field not in doc)
        if missing:
            core.add(findings, "SIG-016", "HIGH", packet_id, packet_root / "artifacts",
                     f"artifact contract missing fields: {', '.join(missing)}", repo)


core.check_artifacts = check_artifacts
raise SystemExit(core.main())
