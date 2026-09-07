#!/usr/bin/env python3
"""Fail closed if Local User Profile metadata becomes login-name authority."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LLD02 = ROOT / "spec/lld/identity-reference"
LLD12 = ROOT / "spec/lld/security-packaging"


def load(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    findings: list[str] = []

    # Persistence authority: one descriptive display_name, never a username/login-name column.
    schema = load(LLD02 / "schema/reference-customer.json")
    tables = {t.get("name"): t for t in schema.get("tables", []) if isinstance(t, dict)}
    profile = tables.get("local_user_profiles")
    if not profile:
        findings.append("local_user_profiles table is missing")
    else:
        columns = [str(c) for c in profile.get("columns", [])]
        if not any(c.startswith("display_name TEXT NOT NULL") for c in columns):
            findings.append("local_user_profiles must persist non-null display_name")
        if any("username" in c.lower() or "login_name" in c.lower() for c in columns):
            findings.append("local_user_profiles persists forbidden username/login-name authority")
        if not any(c.startswith("revision INTEGER NOT NULL") for c in columns):
            findings.append("local_user_profiles display metadata must remain revisioned")

    # Command authority: first run receives descriptive display_name; one explicit edit command owns later changes.
    command_doc = load(LLD02 / "commands/reference-dispatch-settings.json")
    commands = {c.get("name"): c for c in command_doc.get("commands", []) if isinstance(c, dict)}
    create = commands.get("CreateLocalUserProfileIdentity")
    update = commands.get("UpdateLocalUserProfileDisplayName")
    if not create:
        findings.append("CreateLocalUserProfileIdentity command is missing")
    else:
        inputs = [str(x) for x in create.get("input", [])]
        if "display_name" not in inputs:
            findings.append("CreateLocalUserProfileIdentity does not accept display_name metadata")
        if any("username" in x.lower() or "login_name" in x.lower() for x in inputs):
            findings.append("CreateLocalUserProfileIdentity accepts forbidden login-name input")
        create_text = json.dumps(create, sort_keys=True)
        if "Local Administrator" not in create_text:
            findings.append("first-run profile command does not pin server default Local Administrator")
    if not update:
        findings.append("UpdateLocalUserProfileDisplayName command is missing")
    else:
        inputs = [str(x) for x in update.get("input", [])]
        for required in ("base_revision", "display_name", "command_id"):
            if required not in inputs:
                findings.append(f"UpdateLocalUserProfileDisplayName missing {required}")
        update_text = json.dumps(update, sort_keys=True).lower()
        for semantic in ("password", "verifier", "session", "auto-login", "security revision", "encryption"):
            if semantic not in update_text:
                findings.append(f"display-name update does not explicitly exclude {semantic} authority")

    # Legacy/local repository contract cannot expose a username parameter.
    interfaces_text = text(LLD02 / "interfaces.json")
    if "create_once(uow,profile_id,display_name)" not in interfaces_text:
        findings.append("LocalUserProfileRepository does not create using display_name")
    if "update_display_name(uow,profile_id,display_name,base_revision)" not in interfaces_text:
        findings.append("LocalUserProfileRepository lacks explicit display-name update")
    if "profile_id,username" in interfaces_text.replace(" ", "").lower():
        findings.append("legacy Local User Profile repository still accepts username")

    # Cross-packet security provider keeps setup/login password-only and descriptive metadata non-authenticating.
    cross = load(LLD02 / "interfaces/cross-packet-v2.json")
    providers = {p.get("name"): p for p in cross.get("provided", []) if isinstance(p, dict)}
    security_provider = providers.get("LocalUserProfileSecurityProvider")
    if not security_provider:
        findings.append("LocalUserProfileSecurityProvider is missing")
    else:
        provider_text = json.dumps(security_provider, sort_keys=True)
        if "default_display_name='Local Administrator'" not in provider_text:
            findings.append("security provider does not pin server-owned display-name default")
        if "No username is required for setup/login" not in provider_text:
            findings.append("security provider does not explicitly preserve password-only setup/login")

    # Public profile transport is descriptive-only.
    profile_types = load(LLD02 / "types/local-user-profile.json")
    type_defs = profile_types.get("types", {})
    update_req = type_defs.get("UpdateLocalUserProfileDisplayNameRequestV1", {})
    result = type_defs.get("LocalUserProfileV1", {})
    if "display_name" not in update_req.get("body_fields", {}):
        findings.append("profile update DTO lacks display_name")
    if any("username" in str(k).lower() or "login_name" in str(k).lower() for k in update_req.get("body_fields", {})):
        findings.append("profile update DTO exposes login-name field")
    if "display_name" not in result.get("fields", {}):
        findings.append("LocalUserProfileV1 lacks display_name")

    routes = load(LLD02 / "routes/auxiliary-queries.json").get("routes", [])
    route = next((r for r in routes if r.get("handler") == "UpdateLocalUserProfileDisplayName"), None)
    if not route or route.get("path") != "/api/v1/local-user-profile/display-name" or route.get("auth_policy") != "LLD12_BROWSER_MUTATION_V1":
        findings.append("authenticated display-name edit route is missing or misbound")

    # Audit must prove revision transition without duplicating the descriptive value or credentials.
    audit = load(LLD02 / "audit/local-user-profile.json")
    actions = {a.get("action_type"): a for a in audit.get("actions", []) if isinstance(a, dict)}
    if "local_user_profile.display_name_updated" not in actions:
        findings.append("display-name update audit action is missing")
    audit_text = json.dumps(audit, sort_keys=True).lower()
    for forbidden in ("raw_display_name_not_duplicated", "credential_material_forbidden"):
        if forbidden not in audit_text:
            findings.append(f"profile audit does not pin {forbidden}")

    # Regression evidence and UI behavior.
    tests_text = text(LLD02 / "tests/local-user-profile-acceptance.json")
    for case_id in ("LLD02-T038", "LLD02-T039"):
        if case_id not in tests_text:
            findings.append(f"profile acceptance suite missing {case_id}")
    ui_text = text(LLD02 / "ui/reference-state.json")
    for token in ("UpdateLocalUserProfileDisplayName", "display_name", "no username/login-name control"):
        if token not in ui_text:
            findings.append(f"LLD-02 UI handoff missing {token}")

    # Authentication request DTOs remain password-only.
    auth = load(LLD12 / "types/auth.json")
    auth_types = auth.get("types", {})
    for type_name in ("SetupLocalAdminRequestV1", "LoginRequestV1"):
        fields = auth_types.get(type_name, {})
        serialized = json.dumps(fields, sort_keys=True).lower()
        if "username" in serialized or "login_name" in serialized:
            findings.append(f"{type_name} contains forbidden login-name field")
    setup_text = text(LLD12 / "commands/v2/setup-local-admin.json")
    if "no username required" not in setup_text:
        findings.append("SetupLocalAdmin no longer states password-only setup")
    security_ui = text(LLD12 / "ui/security-state.json")
    if "no username control" not in security_ui or "password + confirmation only; username is never required" not in security_ui:
        findings.append("LLD-12 UI no longer proves password-only setup/login")

    # Governance authority must retain editable descriptive display-name decision and no unresolved profile correction.
    decisions = text(ROOT / "docs/DECISIONS.md")
    d059 = next((line for line in decisions.splitlines() if "| D-059 |" in line), "")
    if "display name is editable" not in d059 or "login requires only the Local Administrator password" not in d059:
        findings.append("D-059 no longer pins password-only login plus editable display name")
    lld12_index = load(LLD12 / "_index.json")
    pending = " ".join(str(x) for x in lld12_index.get("pending_global_reconciliation", []))
    if "Local User Profile correction" in pending or "required username" in pending:
        findings.append("LLD-12 still lists Local User Profile display-name correction as unresolved")

    if findings:
        print(f"SOMA Local User Profile authority: HIGH={len(findings)}")
        for finding in findings:
            print(f"[HIGH] {finding}")
        return 1
    print("SOMA Local User Profile authority: HIGH=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
