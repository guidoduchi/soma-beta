#!/usr/bin/env python3
"""Fail closed if LLD-12 loses the governed portable-backup companion set."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "spec/lld/security-packaging"


def load(rel: str):
    with (BASE / rel).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def text(rel: str) -> str:
    return (BASE / rel).read_text(encoding="utf-8")


def main() -> int:
    findings: list[str] = []

    artifact = load("artifacts/portable-backup.json")
    if artifact.get("artifact") != "SOMA_PORTABLE_BACKUP_SET_V1":
        findings.append("artifact authority is not SOMA_PORTABLE_BACKUP_SET_V1")
    if not str(artifact.get("extension", "")).startswith(".somabackupset"):
        findings.append("portable set extension does not identify .somabackupset")
    members = artifact.get("set_members", {})
    expected_members = {
        "payload": "payload.somabackup",
        "manifest": "manifest.json",
        "auth": "auth.json",
    }
    if not isinstance(members, dict) or set(members) != set(expected_members):
        findings.append(f"set_members keys must be exactly {sorted(expected_members)!r}")
    else:
        for key, filename in expected_members.items():
            if not isinstance(members.get(key), dict) or members[key].get("filename") != filename:
                findings.append(f"set member {key} must resolve to {filename}")

    authenticity = artifact.get("detached_auth", {})
    if authenticity.get("mechanism") != "HMAC-SHA-256 over the exact canonical manifest bytes":
        findings.append("detached authenticity mechanism must be exact canonical-manifest HMAC-SHA-256")
    if "SOMA-BACKUP-PORTABLE-AUTH-V1" not in str(authenticity.get("key_derivation", "")):
        findings.append("detached-auth key must use SOMA-BACKUP-PORTABLE-AUTH-V1 HKDF domain")
    recovery = artifact.get("recovery", {})
    if "SOMA-BACKUP-PORTABLE-KEK-V1" not in str(recovery.get("kek", "")):
        findings.append("portable KEK must retain SOMA-BACKUP-PORTABLE-KEK-V1 HKDF domain")
    if "SOMA-BACKUP-PORTABLE-AUTH-V1" not in str(recovery.get("auth_key", "")):
        findings.append("portable auth key must retain SOMA-BACKUP-PORTABLE-AUTH-V1 HKDF domain")
    if "atomic" not in str(artifact.get("finalization_policy", "")).lower():
        findings.append("portable set finalization must be atomic")

    technology = load("technology.json").get("crypto", {})
    if "HMAC-SHA-256" not in str(technology.get("portable_backup_detached_auth", "")):
        findings.append("technology registry does not pin HMAC-SHA-256 detached auth")
    auth_kdf = str(technology.get("portable_backup_auth_kdf", ""))
    if "SOMA-BACKUP-PORTABLE-AUTH-V1" not in auth_kdf or "SOMA-BACKUP-PORTABLE-KEK-V1" not in auth_kdf:
        findings.append("technology registry must state separate AUTH and KEK HKDF domains")

    security_text = text("types/security.json")
    for token in ("set_path", "set_fingerprint", "backup_source_path"):
        if token not in security_text:
            findings.append(f"types/security.json missing complete-set token {token}")

    backup_types = text("types/backup.json")
    for token in ("PortableBackupSetManifestV1", "PortableBackupSetAuthV1", "SOMA-BACKUP-PORTABLE-AUTH-V1"):
        if token not in backup_types:
            findings.append(f"types/backup.json missing {token}")

    create_cmd = text("commands/v2/create-portable-backup.json")
    restore_cmd = text("commands/v2/restore-backup.json")
    restore_algorithm = text("algorithms/restore-verification.json")
    for rel, body in (
        ("commands/v2/create-portable-backup.json", create_cmd),
        ("commands/v2/restore-backup.json", restore_cmd),
        ("algorithms/restore-verification.json", restore_algorithm),
    ):
        if "manifest.json" not in body or "auth.json" not in body:
            findings.append(f"{rel} does not bind both detached companions")
    if "BACKUP_SET_INCOMPLETE" not in restore_cmd:
        findings.append("RestoreBackup does not expose BACKUP_SET_INCOMPLETE")

    errors = load("errors.json").get("errors", [])
    error_codes = {item.get("code") for item in errors if isinstance(item, dict)}
    if "BACKUP_SET_INCOMPLETE" not in error_codes:
        findings.append("errors.json missing BACKUP_SET_INCOMPLETE")

    routes_text = text("routes/backups.json")
    if "BACKUP_SET_INCOMPLETE" not in routes_text or ".somabackupset" not in routes_text:
        findings.append("backup routes do not expose complete-set restore semantics")

    acceptance = text("tests/acceptance.json")
    failure = text("tests/failure-injection.json")
    security = text("tests/security-canaries.json")
    packaging = text("tests/packaging.json")
    for case_id in ("LLD12-A065", "LLD12-A066", "LLD12-A067", "LLD12-A068"):
        if case_id not in acceptance:
            findings.append(f"acceptance suite missing {case_id}")
    for case_id in ("LLD12-F029", "LLD12-F030", "LLD12-F031"):
        if case_id not in failure:
            findings.append(f"failure suite missing {case_id}")
    if "LLD12-S025" not in security:
        findings.append("security canaries missing LLD12-S025")
    if "LLD12-P017" not in packaging:
        findings.append("packaging suite missing LLD12-P017")

    trace = text("tests/traceability.json")
    for token in ("BETA-REQ-0037", "LLD12-A068", "LLD12-F031", "LLD12-S025", "LLD12-P017"):
        if token not in trace:
            findings.append(f"traceability missing {token}")

    if findings:
        print(f"SOMA portable backup set closure: HIGH={len(findings)}")
        for finding in findings:
            print(f"[HIGH] {finding}")
        return 1
    print("SOMA portable backup set closure: HIGH=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
