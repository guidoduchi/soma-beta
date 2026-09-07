#!/usr/bin/env python3
"""Fail closed if Local User Profile regains login-name authority.

Beta 1.0 authenticates the single local administrator by password only. LLD-02
owns immutable actor/profile identity plus descriptive display_name metadata;
LLD-12 owns credential/session security. This checker proves the corrected
cross-packet representation and the editable-display-name path stay intact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
L2 = ROOT / "spec/lld/identity-reference"
L12 = ROOT / "spec/lld/security-packaging"


def load(base: Path, rel: str):
    with (base / rel).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def text(base: Path, rel: str) -> str:
    return (base / rel).read_text(encoding="utf-8")


def main() -> int:
    findings: list[str] = []

    schema = load(L2, "schema/reference-customer.json")
    profile_table = next((t for t in schema.get("tables", []) if t.get("name") == "local_user_profiles"), None)
    if not profile_table:
        findings.append("local_user_profiles table missing")
    else:
        columns = profile_table.get("columns", [])
        if not any(str(c).startswith("display_name TEXT NOT NULL") for c in columns):
            findings.append("local_user_profiles lacks required display_name column")
        if any(str(c).lower().startswith("username ") for c in columns):
            findings.append("local_user_profiles still persists username column")

    command_text = text(L2, "commands/reference-dispatch-settings.json")
    for token in ("CreateLocalUserProfileIdentity", "display_name", "UpdateLocalUserProfileDisplayName", "local_user_profile.display_name_updated"):
        if token not in command_text:
            findings.append(f"profile command authority missing {token}")
    if '"input":["username"' in command_text or 'profile_id,username' in command_text:
        findings.append("profile command authority still accepts username input")

    legacy_interfaces = text(L2, "interfaces.json")
    if "LocalUserProfileRepository" not in legacy_interfaces or "update_display_name" not in legacy_interfaces:
        findings.append("LLD-02 repository interface missing display-name authority")
    if "create_once(uow,profile_id,username)" in legacy_interfaces:
        findings.append("legacy Local User Profile repository still accepts username")

    canonical = text(L2, "interfaces/cross-packet-v2.json")
    if "LocalUserProfileSecurityProvider" not in canonical or "default_display_name='Local Administrator'" not in canonical:
        findings.append("canonical LLD-02 security provider missing server-default display-name contract")

    type_text = text(L2, "types/local-user-profile.json")
    for token in ("UpdateLocalUserProfileDisplayNameRequestV1", "LocalUserProfileV1", "display_name"):
        if token not in type_text:
            findings.append(f"Local User Profile transport missing {token}")

    route_text = text(L2, "routes/auxiliary-queries.json")
    if "/api/v1/local-user-profile/display-name" not in route_text or "UpdateLocalUserProfileDisplayName" not in route_text:
        findings.append("display-name mutation route missing")

    audit_text = text(L2, "audit/local-user-profile.json")
    if "local_user_profile.display_name_updated" not in audit_text or "prior_revision" not in audit_text or "new_revision" not in audit_text:
        findings.append("display-name audit contract missing")

    tests = text(L2, "tests/local-user-profile-acceptance.json")
    for case_id in ("LLD02-T038", "LLD02-T039"):
        if case_id not in tests:
            findings.append(f"profile regression suite missing {case_id}")

    trace = text(L2, "tests/traceability.json") + text(L2, "tests/traceability/commands-b.json")
    for token in ("BETA-REQ-0035", "UpdateLocalUserProfileDisplayName", "LLD02-T039", "LocalUserProfileSecurityProvider"):
        if token not in trace:
            findings.append(f"profile traceability missing {token}")

    auth_types = load(L12, "types/auth.json").get("types", {})
    setup = auth_types.get("SetupLocalAdminRequestV1", {})
    login = auth_types.get("LoginRequestV1", {})
    setup_keys = set(setup.keys()) | set((setup.get("body_fields") or {}).keys())
    login_keys = set(login.keys()) | set((login.get("body_fields") or {}).keys())
    if "username" in setup_keys or "username" in login_keys:
        findings.append("LLD-12 setup/login DTO exposes username field")

    ui_text = text(L12, "ui/security-state.json")
    if "profile_display_name" not in ui_text or "UpdateLocalUserProfileDisplayName" not in ui_text:
        findings.append("security/settings UI does not expose descriptive profile display-name edit")
    if "no username control" not in ui_text or "password + confirmation only; username is never required" not in ui_text:
        findings.append("password-only UI guard missing")

    if findings:
        print(f"SOMA Local User Profile identity closure: MEDIUM={len(findings)}")
        for finding in findings:
            print(f"[MEDIUM] {finding}")
        return 1
    print("SOMA Local User Profile identity closure: MEDIUM=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
