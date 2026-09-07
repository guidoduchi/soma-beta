#!/usr/bin/env python3
"""Fail closed if Local User Profile regains login-name authority.

Beta 1.0 authenticates the single local administrator by password only. LLD-02
owns immutable actor/profile identity plus editable descriptive display_name
metadata; LLD-12 owns credential/session security. Explanatory text may mention
"username" only to forbid it—the checker rejects username/login-name as schema,
command, repository or public-auth authority.
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
    profile_table = next((t for t in schema.get("tables", []) if isinstance(t, dict) and t.get("name") == "local_user_profiles"), None)
    if not profile_table:
        findings.append("local_user_profiles table missing")
    else:
        columns = [str(c) for c in profile_table.get("columns", [])]
        if not any(c.startswith("display_name TEXT NOT NULL") for c in columns):
            findings.append("local_user_profiles lacks required display_name column")
        if any("username" in c.lower() or "login_name" in c.lower() for c in columns):
            findings.append("local_user_profiles persists username/login-name authority")
        if not any(c.startswith("revision INTEGER NOT NULL") for c in columns):
            findings.append("local_user_profiles display metadata is not revisioned")

    command_doc = load(L2, "commands/reference-dispatch-settings.json")
    commands = {c.get("name"): c for c in command_doc.get("commands", []) if isinstance(c, dict)}
    create = commands.get("CreateLocalUserProfileIdentity")
    update = commands.get("UpdateLocalUserProfileDisplayName")
    if not create:
        findings.append("CreateLocalUserProfileIdentity command missing")
    else:
        inputs = [str(x) for x in create.get("input", [])]
        if "display_name" not in inputs:
            findings.append("CreateLocalUserProfileIdentity lacks display_name metadata")
        if any("username" in x.lower() or "login_name" in x.lower() for x in inputs):
            findings.append("CreateLocalUserProfileIdentity accepts forbidden login-name input")
        if "Local Administrator" not in json.dumps(create, sort_keys=True):
            findings.append("first-run profile command lacks server default Local Administrator")
    if not update:
        findings.append("UpdateLocalUserProfileDisplayName command missing")
    else:
        inputs = [str(x) for x in update.get("input", [])]
        for required in ("base_revision", "display_name", "command_id"):
            if required not in inputs:
                findings.append(f"UpdateLocalUserProfileDisplayName missing {required}")
        update_text = json.dumps(update, sort_keys=True).lower()
        for semantic in ("password", "verifier", "session", "auto-login", "security revision", "encryption"):
            if semantic not in update_text:
                findings.append(f"display-name update does not explicitly exclude {semantic} authority")

    legacy_interfaces = text(L2, "interfaces.json")
    if "LocalUserProfileRepository" not in legacy_interfaces:
        findings.append("LLD-02 LocalUserProfileRepository missing")
    if "create_once(uow,profile_id,display_name)" not in legacy_interfaces:
        findings.append("LocalUserProfileRepository does not create using display_name")
    if "update_display_name(uow,profile_id,display_name,base_revision)" not in legacy_interfaces:
        findings.append("LocalUserProfileRepository lacks display-name update")
    normalized_interfaces = legacy_interfaces.replace(" ", "").lower()
    if "create_once(uow,profile_id,username)" in normalized_interfaces or "profile_id,username" in normalized_interfaces:
        findings.append("legacy Local User Profile repository still accepts username")

    canonical = load(L2, "interfaces/cross-packet-v2.json")
    providers = {p.get("name"): p for p in canonical.get("provided", []) if isinstance(p, dict)}
    security_provider = providers.get("LocalUserProfileSecurityProvider")
    if not security_provider:
        findings.append("LocalUserProfileSecurityProvider missing")
    else:
        provider_text = json.dumps(security_provider, sort_keys=True)
        if "default_display_name='Local Administrator'" not in provider_text:
            findings.append("canonical provider lacks server-default display-name contract")
        if "No username is required for setup/login" not in provider_text:
            findings.append("canonical provider no longer proves password-only setup/login")

    profile_types = load(L2, "types/local-user-profile.json").get("types", {})
    update_req = profile_types.get("UpdateLocalUserProfileDisplayNameRequestV1", {})
    profile_result = profile_types.get("LocalUserProfileV1", {})
    body_fields = update_req.get("body_fields", {})
    if "display_name" not in body_fields:
        findings.append("profile update DTO lacks display_name")
    if any("username" in str(k).lower() or "login_name" in str(k).lower() for k in body_fields):
        findings.append("profile update DTO exposes login-name field")
    if "display_name" not in profile_result.get("fields", {}):
        findings.append("LocalUserProfileV1 lacks display_name")

    routes = load(L2, "routes/auxiliary-queries.json").get("routes", [])
    route = next((r for r in routes if isinstance(r, dict) and r.get("handler") == "UpdateLocalUserProfileDisplayName"), None)
    if not route:
        findings.append("display-name mutation route missing")
    elif route.get("path") != "/api/v1/local-user-profile/display-name" or route.get("auth_policy") != "LLD12_BROWSER_MUTATION_V1":
        findings.append("display-name mutation route is misbound")

    audit = load(L2, "audit/actions.json")
    actions = {a.get("action_type"): a for a in audit.get("actions", []) if isinstance(a, dict)}
    if "local_user_profile.display_name_updated" not in actions:
        findings.append("display-name update audit action missing")
    audit_text = json.dumps(audit, sort_keys=True).lower()
    for guard in ("raw_display_name_not_duplicated", "credential_material_forbidden"):
        if guard not in audit_text:
            findings.append(f"profile audit does not pin {guard}")

    tests = text(L2, "tests/local-user-profile-acceptance.json")
    for case_id in ("LLD02-T038", "LLD02-T039"):
        if case_id not in tests:
            findings.append(f"profile regression suite missing {case_id}")
    trace = text(L2, "tests/traceability.json") + text(L2, "tests/traceability/commands-b.json")
    for token in ("BETA-REQ-0035", "UpdateLocalUserProfileDisplayName", "LLD02-T039", "LocalUserProfileSecurityProvider"):
        if token not in trace:
            findings.append(f"profile traceability missing {token}")

    ui_text = text(L2, "ui/reference-state.json")
    for token in ("UpdateLocalUserProfileDisplayName", "display_name", "no username/login-name control"):
        if token not in ui_text:
            findings.append(f"LLD-02 UI handoff missing {token}")

    auth_types = load(L12, "types/auth.json").get("types", {})
    for type_name in ("SetupLocalAdminRequestV1", "LoginRequestV1"):
        serialized = json.dumps(auth_types.get(type_name, {}), sort_keys=True).lower()
        if "username" in serialized or "login_name" in serialized:
            findings.append(f"{type_name} contains forbidden login-name field")
    setup_text = text(L12, "commands/v2/setup-local-admin.json")
    if "no username required" not in setup_text:
        findings.append("SetupLocalAdmin no longer states password-only setup")
    security_ui = text(L12, "ui/security-state.json")
    for token in ("profile_display_name", "UpdateLocalUserProfileDisplayName", "no username control", "password + confirmation only; username is never required"):
        if token not in security_ui:
            findings.append(f"LLD-12 UI authority missing {token}")

    decisions = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")
    d059 = next((line for line in decisions.splitlines() if "| D-059 |" in line), "")
    if "login requires only the Local Administrator password" not in d059 or "display name is editable" not in d059:
        findings.append("D-059 no longer pins password-only login plus editable display name")

    lld12_index = load(L12, "_index.json")
    pending = " ".join(str(x) for x in lld12_index.get("pending_global_reconciliation", []))
    if "Local User Profile correction" in pending or "required username" in pending:
        findings.append("LLD-12 still lists Local User Profile correction as unresolved")

    if findings:
        print(f"SOMA Local User Profile identity closure: MEDIUM={len(findings)}")
        for finding in findings:
            print(f"[MEDIUM] {finding}")
        return 1
    print("SOMA Local User Profile identity closure: MEDIUM=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
