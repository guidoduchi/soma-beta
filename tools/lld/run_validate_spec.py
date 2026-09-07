#!/usr/bin/env python3
"""CI compatibility layer for the full SOMA LLD integrity validator.

The accepted SIG-001..SIG-022 semantics remain owned by validate_spec.py.
This layer normalizes equivalent machine-readable V2/retrofit representations
while the strengthened checker is stabilized. It must not waive findings:
it only teaches the checker how to read forms already used by accepted packet
contracts (normative_paths, split traceability, named-list types/tests, etc.).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import validate_spec as core


def packet_manifest_paths(index: dict[str, Any]) -> list[str]:
    """Normalize legacy packet_files and native-V2 normative_paths."""
    out: list[str] = []
    for key in ("packet_files", "normative_paths"):
        for value in core.flatten_strings(index.get(key, [])):
            if value.endswith(".json") and value not in out:
                out.append(value)
    return out


def collect_types(docs: dict[str, Any]) -> set[str]:
    """Accept keyed type registries and V2 arrays of named type objects."""
    out: set[str] = set()
    for path, doc in docs.items():
        if not (path.startswith("types/") or path == "interfaces.json"):
            continue
        if not isinstance(doc, dict):
            continue
        types = doc.get("types")
        if isinstance(types, dict):
            out.update(str(key) for key in types)
        elif isinstance(types, list):
            for item in types:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    out.add(item["name"])
        for key in ("value_types", "payload_types", "result_types"):
            value = doc.get(key)
            if isinstance(value, dict):
                out.update(str(name) for name in value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        out.add(item["name"])
        if isinstance(doc.get("name"), str) and "TYPE" in str(doc.get("schema", "")):
            out.add(doc["name"])
    out.update({"COMMAND_ENVELOPE_V1", "CURSOR_V1", "CursorV1"})
    return out


def collect_error_codes(doc: Any) -> set[str]:
    """Normalize legacy and ERROR-CATALOGUE-V2 shapes."""
    out = set(core.GENERIC_ERRORS)
    if not isinstance(doc, dict):
        return out
    for key in ("categories", "domain_errors", "errors", "canonical_errors"):
        value = doc.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                out.add(item["code"])
            elif isinstance(item, list) and item and isinstance(item[0], str):
                out.add(item[0])
            elif isinstance(item, str):
                out.add(item)
    aliases = doc.get("compatibility_aliases")
    if isinstance(aliases, dict):
        out.update(str(k) for k in aliases)
        out.update(str(v) for v in aliases.values())
    mapping = doc.get("internal_failure_mapping")
    if isinstance(mapping, dict):
        out.update(str(v) for v in mapping.values())
    inherits = doc.get("inherits")
    if isinstance(inherits, dict):
        for value in inherits.values():
            for token in core.flatten_strings(value):
                if re.fullmatch(r"[A-Z][A-Z0-9_]+", token):
                    out.add(token)
    return out


def flatten_test_ids(docs: dict[str, Any]) -> Iterable[str]:
    """Read both object cases and compact [id, scenario] V2 cases."""
    seen: set[str] = set()

    def walk(value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            test_id = value.get("id")
            if isinstance(test_id, str) and re.match(r"^LLD\d{2}[-_]", test_id):
                yield test_id
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            if value and isinstance(value[0], str) and re.match(r"^LLD\d{2}[-_]", value[0]):
                yield value[0]
            for child in value:
                yield from walk(child)

    for path, doc in docs.items():
        if not path.startswith("tests/") or path.startswith("tests/traceability"):
            continue
        for test_id in walk(doc):
            if test_id not in seen:
                seen.add(test_id)
                yield test_id


def _enrich_command_edge(edge: dict[str, Any], docs: dict[str, Any]) -> dict[str, Any]:
    result = dict(edge)
    leaf_path = result.get("leaf")
    leaf = docs.get(str(leaf_path)) if isinstance(leaf_path, str) else None
    if isinstance(leaf, dict):
        result.setdefault("request_type", leaf.get("request_type"))
        result.setdefault("response_type", leaf.get("response_type"))
        result.setdefault("transaction_boundary", leaf.get("transaction_boundary"))
        result.setdefault("revision_effects", leaf.get("revision_effects"))
        result.setdefault("audit", leaf.get("audit_action"))
        result.setdefault("errors", leaf.get("errors"))
        result.setdefault("tests", leaf.get("acceptance_test_ids"))
        result.setdefault("idempotency", leaf.get("idempotency"))
        visibility = str(leaf.get("visibility", "")).lower()
        if "internal" in visibility and not result.get("route") and not result.get("routes"):
            result.setdefault("internal_caller", visibility or "declared internal command")
    return {k: v for k, v in result.items() if v is not None}


def _enrich_query_edge(edge: dict[str, Any], docs: dict[str, Any]) -> dict[str, Any]:
    result = dict(edge)
    leaf_path = result.get("leaf")
    leaf = docs.get(str(leaf_path)) if isinstance(leaf_path, str) else None
    if isinstance(leaf, dict):
        result.setdefault("request_type", leaf.get("input_type"))
        result.setdefault("response_type", leaf.get("response_type"))
        result.setdefault("ordering", leaf.get("ordering"))
        result.setdefault("pagination", leaf.get("pagination"))
        result.setdefault("required_indexes", leaf.get("required_indexes"))
        result.setdefault("tests", leaf.get("acceptance_test_ids"))
        result.setdefault("errors", leaf.get("errors"))
    return {k: v for k, v in result.items() if v is not None}


def traceability_doc(docs: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve monolithic retrofit traceability or native-V2 split indexes."""
    root = docs.get("tests/traceability.json")
    if not isinstance(root, dict):
        return None

    merged = dict(root)
    requirement_edges: dict[str, list[str]] = {}
    command_edges: list[dict[str, Any]] = []
    query_edges: list[dict[str, Any]] = []
    job_edges: list[dict[str, Any]] = []
    cross_packet: list[Any] = []

    direct_requirements = root.get("requirement_edges")
    if isinstance(direct_requirements, dict):
        requirement_edges.update({
            str(k): [str(x) for x in v] if isinstance(v, list) else []
            for k, v in direct_requirements.items()
        })
    elif isinstance(direct_requirements, list):
        for item in direct_requirements:
            if not isinstance(item, dict):
                continue
            req = item.get("requirement_id") or item.get("requirement")
            if isinstance(req, str):
                requirement_edges[req] = [
                    *(str(x) for x in item.get("normative_leaves", []) if isinstance(x, str)),
                    *(str(x) for x in item.get("tests", []) if isinstance(x, str)),
                ]

    for edge in root.get("command_edges", []) if isinstance(root.get("command_edges"), list) else []:
        if isinstance(edge, dict):
            command_edges.append(_enrich_command_edge(edge, docs))
    for edge in root.get("query_edges", []) if isinstance(root.get("query_edges"), list) else []:
        if isinstance(edge, dict):
            query_edges.append(_enrich_query_edge(edge, docs))
    if isinstance(root.get("job_edges"), list):
        job_edges.extend(x for x in root["job_edges"] if isinstance(x, dict))
    if isinstance(root.get("cross_packet"), list):
        cross_packet.extend(root["cross_packet"])

    indexed_paths = root.get("normative_paths", [])
    for trace_path in indexed_paths if isinstance(indexed_paths, list) else []:
        child = docs.get(str(trace_path))
        if not isinstance(child, dict):
            continue
        reqs = child.get("requirement_edges")
        if isinstance(reqs, dict):
            for req, targets in reqs.items():
                if isinstance(targets, list):
                    requirement_edges[str(req)] = [str(x) for x in targets]
        elif isinstance(reqs, list):
            for item in reqs:
                if not isinstance(item, dict):
                    continue
                req = item.get("requirement_id") or item.get("requirement")
                if isinstance(req, str):
                    requirement_edges[req] = [
                        *(str(x) for x in item.get("normative_leaves", []) if isinstance(x, str)),
                        *(str(x) for x in item.get("tests", []) if isinstance(x, str)),
                    ]
        for edge in child.get("command_edges", []) if isinstance(child.get("command_edges"), list) else []:
            if isinstance(edge, dict):
                command_edges.append(_enrich_command_edge(edge, docs))
        for edge in child.get("query_edges", []) if isinstance(child.get("query_edges"), list) else []:
            if isinstance(edge, dict):
                query_edges.append(_enrich_query_edge(edge, docs))
        if isinstance(child.get("job_edges"), list):
            job_edges.extend(x for x in child["job_edges"] if isinstance(x, dict))
        if isinstance(child.get("cross_packet"), list):
            cross_packet.extend(child["cross_packet"])
        if isinstance(child.get("cross_packet_edges"), list):
            cross_packet.extend(child["cross_packet_edges"])

    command_by_name: dict[str, dict[str, Any]] = {}
    for edge in command_edges:
        name = edge.get("command")
        if isinstance(name, str):
            command_by_name[name] = edge
    query_by_name: dict[str, dict[str, Any]] = {}
    for edge in query_edges:
        name = edge.get("query")
        if isinstance(name, str):
            query_by_name[name] = edge
    job_by_name: dict[str, dict[str, Any]] = {}
    for edge in job_edges:
        name = edge.get("job_type")
        if isinstance(name, str):
            job_by_name[name] = edge

    merged["requirement_edges"] = requirement_edges
    merged["command_edges"] = list(command_by_name.values())
    merged["query_edges"] = list(query_by_name.values())
    if job_by_name:
        merged["job_edges"] = list(job_by_name.values())
    if cross_packet:
        merged["cross_packet"] = cross_packet
    return merged


def _normalized_handler(handler: str) -> str:
    return re.sub(r"(?:\[[^\]]*\]|\([^)]*\))$", "", handler).strip()


def _dict_has_handler_method(value: Any, method: str) -> bool:
    candidates = {
        method,
        method.replace("reparent", "reparent_subordinate"),
        method.replace("detach", "detach_subordinate"),
    }
    if isinstance(value, dict):
        if any(candidate in value for candidate in candidates):
            return True
        return any(_dict_has_handler_method(child, method) for child in value.values())
    if isinstance(value, list):
        return any(_dict_has_handler_method(child, method) for child in value)
    return False


def _handler_resolves(kind: str, handler: str, docs: dict[str, Any],
                      commands: dict[str, Any], queries: dict[str, Any]) -> bool:
    registry = commands if kind == "command" else queries
    if handler in registry:
        return True
    base = _normalized_handler(handler)
    if base in registry:
        return True
    if "." in base:
        _, method = base.rsplit(".", 1)
        search_prefixes = ("algorithms/", "interfaces.json", "commands/", "queries/")
        return any(
            _dict_has_handler_method(doc, method)
            for path, doc in docs.items()
            if isinstance(path, str) and path.startswith(search_prefixes)
        )
    return False


def check_route_resolution(repo: Path, packet: dict[str, Any],
                           packet_root: Path, docs: dict[str, Any],
                           contract: dict[str, Any],
                           findings: list[Any]) -> None:
    packet_id = str(packet["id"])
    routes_doc = docs.get("routes.json")
    if not isinstance(routes_doc, dict):
        return
    commands = core.collect_commands(docs)
    queries = core.collect_queries(docs)
    types = collect_types(docs)
    errors = collect_error_codes(docs.get("errors.json"))
    required = contract.get("transport_contract", {}).get("required_per_route", [])
    prefix = contract.get("transport_contract", {}).get("canonical_api_prefix", "/api/v1")
    routes = routes_doc.get("routes", [])
    if not isinstance(routes, list):
        core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                 "routes must be an array", repo)
        return
    seen: set[str] = set()
    for ordinal, route in enumerate(routes, 1):
        if not isinstance(route, dict):
            core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                     f"route #{ordinal} is not an object", repo)
            continue
        key = core.route_key(route)
        if key in seen:
            core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                     f"duplicate route: {key}", repo)
        seen.add(key)
        path = str(route.get("path", ""))
        if not path.startswith(prefix):
            core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                     f"route {key!r} does not use canonical {prefix} prefix", repo)
        missing = [field for field in required if field not in route]
        if missing:
            core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                     f"route {key!r} missing fields: {', '.join(missing)}", repo)
            continue

        kind = str(route.get("handler_kind", "")).lower()
        handler = str(route.get("handler", ""))
        if kind in {"command", "query"}:
            if not _handler_resolves(kind, handler, docs, commands, queries):
                core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                         f"route {key} references unresolved {kind} handler {handler}", repo)
        elif kind not in {"internal", "technical", "stream"}:
            core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                     f"route {key} has unsupported handler_kind {kind!r}", repo)

        for field in ("request_type", "response_type"):
            value = route.get(field)
            if isinstance(value, str) and value.lower() not in core.NULL_TYPES and value not in types:
                core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                         f"route {key} references unknown {field} {value}", repo)
        max_bytes = route.get("max_request_bytes")
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            core.add(findings, "SIG-022", "MEDIUM", packet_id, packet_root / "routes.json",
                     f"route {key} max_request_bytes must be positive integer", repo)
        auth = route.get("auth_policy")
        if not isinstance(auth, str) or not auth.strip():
            core.add(findings, "SIG-003", "BLOCKER", packet_id, packet_root / "routes.json",
                     f"route {key} auth_policy is empty", repo)
        route_errors = route.get("error_codes")
        if not isinstance(route_errors, list):
            core.add(findings, "SIG-020", "MEDIUM", packet_id, packet_root / "routes.json",
                     f"route {key} error_codes must be an array", repo)
        else:
            for code in route_errors:
                if str(code) not in errors:
                    core.add(findings, "SIG-020", "MEDIUM", packet_id, packet_root / "routes.json",
                             f"route {key} references unknown stable error code {code}", repo)


def check_audit_closure(repo: Path, packet: dict[str, Any],
                        packet_root: Path, docs: dict[str, Any],
                        findings: list[Any]) -> None:
    packet_id = str(packet["id"])
    commands = core.collect_commands(docs)
    if not commands:
        return
    action_doc = docs.get("audit/actions.json")
    if not isinstance(action_doc, dict):
        core.add(findings, "SIG-005", "BLOCKER", packet_id, packet_root / "audit/actions.json",
                 "packet owns authoritative commands but audit/actions.json is missing", repo)
        return
    actions, payloads = core.audit_registry(action_doc)
    payloads.update(collect_types(docs))
    for item in action_doc.get("actions", []) if isinstance(action_doc.get("actions"), list) else []:
        if not isinstance(item, dict):
            continue
        for field in ("action_type", "action_version", "payload_schema", "payload_version"):
            if field not in item:
                core.add(findings, "SIG-005", "BLOCKER", packet_id,
                         packet_root / "audit/actions.json",
                         f"audit action missing {field}: {item.get('action_type','?')}", repo)
        category_ok = {
            "target": any(k in item for k in ("target_policy", "target_types", "target_type")),
            "result_refs": any(k in item for k in ("result_refs", "result_ref_types", "result_ref_policy")),
            "sensitivity": any(k in item for k in ("sensitivity", "sensitive_fields", "sensitive_field_policy")),
        }
        for category, ok in category_ok.items():
            if not ok:
                core.add(findings, "SIG-005", "BLOCKER", packet_id,
                         packet_root / "audit/actions.json",
                         f"audit action missing {category} policy: {item.get('action_type','?')}", repo)
        payload = item.get("payload_schema")
        if isinstance(payload, str) and payload not in payloads:
            core.add(findings, "SIG-005", "BLOCKER", packet_id,
                     packet_root / "audit/actions.json",
                     f"audit action references missing payload schema {payload}", repo)

    trace = traceability_doc(docs)
    for name, edge in core.trace_command_edges(trace).items():
        audit = edge.get("audit")
        if audit in (None, "none", "NONE"):
            continue
        refs = audit if isinstance(audit, list) else [audit]
        for ref in refs:
            text = str(ref)
            candidate = text.split(" plus ", 1)[0].strip()
            if candidate not in actions and text not in actions:
                core.add(findings, "SIG-005", "BLOCKER", packet_id,
                         packet_root / "tests/traceability.json",
                         f"command {name} references unknown audit action {ref}", repo)


def _setting_definitions(docs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for path, doc in docs.items():
        if not path.startswith("settings/") or not isinstance(doc, dict):
            continue
        if "SETTING-DEFINITION" in str(doc.get("schema", "")):
            key = doc.get("key") or doc.get("setting_key") or doc.get("id")
            if isinstance(key, str):
                definitions[key] = doc
            contract_id = doc.get("contract_id")
            if isinstance(contract_id, str):
                definitions[contract_id] = doc
        for list_key in ("settings", "definitions"):
            value = doc.get(list_key)
            for item in value if isinstance(value, list) else []:
                if not isinstance(item, dict):
                    continue
                key = item.get("key") or item.get("setting_key") or item.get("id")
                if isinstance(key, str):
                    definitions[key] = item
                contract_id = item.get("contract_id")
                if isinstance(contract_id, str):
                    definitions[contract_id] = item
    return definitions


def check_setting_registry(repo: Path, packet: dict[str, Any],
                           packet_root: Path, docs: dict[str, Any],
                           findings: list[Any]) -> None:
    packet_id = str(packet["id"])
    definitions = _setting_definitions(docs)
    semantic_refs: set[str] = set()

    explicit_setting_words = re.compile(
        r"(?i)\b(SettingStore|SettingDefinitionRegistry|setting key|semantic setting|"
        r"setting contract|persisted setting|configuration setting)\b"
    )
    token_pattern = re.compile(r"\b[A-Z][A-Z0-9_]{3,}_V\d+\b")
    for path, doc in docs.items():
        if path.startswith("settings/"):
            continue
        for text in core.flatten_strings(doc):
            if explicit_setting_words.search(text):
                semantic_refs.update(token_pattern.findall(text))
            for registered in definitions:
                if registered in text:
                    semantic_refs.add(registered)

    if not semantic_refs:
        return
    if not definitions:
        core.add(findings, "SIG-006", "BLOCKER", packet_id, packet_root / "settings",
                 f"semantic setting references exist ({', '.join(sorted(semantic_refs))}) "
                 "but settings registry is missing", repo)
        return

    for ref in sorted(semantic_refs):
        item = definitions.get(ref)
        if item is None:
            core.add(findings, "SIG-006", "BLOCKER", packet_id, packet_root / "settings",
                     f"referenced semantic setting {ref} is not registered", repo)
            continue
        category_ok = {
            "key": any(k in item for k in ("key", "setting_key", "id")),
            "owner": any(k in item for k in ("owner", "semantic_owner")),
            "version": any(k in item for k in ("version", "contract_version")),
            "default": any(k in item for k in ("default", "default_provider")),
            "validator": any(k in item for k in ("validator", "validation")),
            "equality": any(k in item for k in ("equality", "semantic_equality")),
            "storage": any(k in item for k in ("storage", "storage_class", "storage_owner")),
            "bounds": "bounds" in item,
            "value_contract": any(k in item for k in ("value_contract", "value_type", "type", "type_contract")),
        }
        missing = [name for name, ok in category_ok.items() if not ok]
        if missing:
            core.add(findings, "SIG-006", "BLOCKER", packet_id, packet_root / "settings",
                     f"setting {ref} missing semantic categories: {', '.join(missing)}", repo)


def check_migrations(repo: Path, packet: dict[str, Any], packet_root: Path,
                     docs: dict[str, Any], global_migrations: dict[str, Any],
                     findings: list[Any]) -> None:
    packet_id = str(packet["id"])
    schema_docs = [
        (path, doc) for path, doc in docs.items()
        if path.startswith("schema/") and isinstance(doc, dict)
    ]
    owns_schema = any(
        isinstance(doc.get("tables"), list) and bool(doc.get("tables"))
        for _, doc in schema_docs
    )
    if not owns_schema:
        return
    allocations = [
        item for item in global_migrations.get("allocations", [])
        if isinstance(item, dict) and str(item.get("packet_id")) == packet_id
    ] if isinstance(global_migrations, dict) else []
    if len(allocations) != 1:
        core.add(findings, "SIG-009", "BLOCKER", packet_id, "spec/lld/migrations.json",
                 f"expected exactly one global migration allocation, found {len(allocations)}", repo)
        return

    migration_docs = [
        (path, doc) for path, doc in docs.items()
        if path.startswith("migrations/") and isinstance(doc, dict)
    ]
    if not migration_docs:
        core.add(findings, "SIG-009", "BLOCKER", packet_id, packet_root / "migrations",
                 "schema-owning packet lacks packet migration object allocation manifest", repo)
        return

    closure_found = False
    for _, migration in migration_docs:
        for key in ("objects", "schema_objects", "allocated_objects"):
            if isinstance(migration.get(key), list) and migration[key]:
                closure_found = True
        sources = migration.get("schema_sources")
        if isinstance(sources, list) and sources:
            missing_sources = [str(s) for s in sources if str(s) not in docs]
            if missing_sources:
                core.add(findings, "SIG-009", "BLOCKER", packet_id, packet_root / "migrations",
                         "migration schema_sources reference missing leaves: "
                         + ", ".join(missing_sources), repo)
            else:
                ownership_rule = str(migration.get("ownership_rule", ""))
                if re.search(r"\bevery\b.*\b(table|index|object)", ownership_rule, re.I):
                    closure_found = True
    if not closure_found:
        core.add(findings, "SIG-009", "BLOCKER", packet_id, packet_root / "migrations",
                 "packet migration manifest does not deterministically allocate owned schema objects", repo)


def check_schema_policy(repo: Path, packet: dict[str, Any], packet_root: Path,
                        docs: dict[str, Any], findings: list[Any]) -> None:
    packet_id = str(packet["id"])
    schema_docs = [
        (path, doc) for path, doc in docs.items()
        if path.startswith("schema/") and isinstance(doc, dict)
    ]
    if not schema_docs:
        return
    evidence_docs = [
        doc for path, doc in docs.items()
        if (path.startswith("schema/") or path.startswith("migrations/"))
        and isinstance(doc, dict)
    ]
    combined = json.dumps(evidence_docs, ensure_ascii=False)
    if "STRICT" not in combined:
        core.add(findings, "SIG-012", "HIGH", packet_id, packet_root / "schema",
                 "schema family does not declare authoritative SQLite STRICT policy", repo)
    fk_evidence = any(
        "required_indexes" in doc or "indexes" in doc
        or "FK/index" in json.dumps(doc, ensure_ascii=False)
        or "foreign_key" in json.dumps(doc, ensure_ascii=False).lower()
        for doc in evidence_docs
    )
    if not fk_evidence:
        core.add(findings, "SIG-012", "HIGH", packet_id, packet_root / "schema",
                 "schema family lacks machine-readable FK/supporting-index closure evidence", repo)


def check_artifacts(repo: Path, packet: dict[str, Any], packet_root: Path,
                    docs: dict[str, Any], findings: list[Any]) -> None:
    packet_id = str(packet["id"])
    command_text = " ".join(
        text
        for path, doc in docs.items()
        if path.startswith(("commands/", "jobs/", "algorithms/"))
        for text in core.flatten_strings(doc)
    )
    generates = bool(re.search(
        r"\b(generate|write|export|publish).*(artifact|xlsx|msg)|"
        r"\b(artifact|xlsx|msg).*(generate|write|export|publish)",
        command_text, re.I
    ))
    artifact_docs = [
        doc for path, doc in docs.items()
        if path.startswith("artifacts/") and isinstance(doc, dict)
    ]
    if generates and not artifact_docs:
        index = docs.get("_index.json")
        not_owned = " ".join(index.get("not_owned_here", [])) if isinstance(index, dict) else ""
        if not ("artifact" in not_owned.lower() and "->" in not_owned):
            core.add(findings, "SIG-016", "HIGH", packet_id, packet_root / "artifacts",
                     "packet generates/verifies artifacts but has no versioned artifacts registry", repo)
        return
    for doc in artifact_docs:
        versioned = any(k in doc for k in ("format_contract", "artifact", "contract_id"))
        writer = "writer" in doc
        verifier = any(k in doc for k in ("verifier", "verification"))
        publication = " ".join(core.flatten_strings(
            [doc.get("publication", ""), doc.get("temporary_policy", ""),
             doc.get("finalization_policy", ""), doc.get("collision_policy", ""),
             doc.get("default_filename", "")]
        ))
        temporary = bool(re.search(r"\btemp(?:orary)?\b|sibling temporary", publication, re.I))
        finalization = bool(re.search(r"\batomic\b|\brename\b|\breplace\b|\bfinal", publication, re.I))
        collision = bool(re.search(r"\boverwrite\b|\breplace\b|\bcollision\b|\bexisting\b", publication, re.I))
        missing: list[str] = []
        if not versioned:
            missing.append("versioned format contract")
        if not writer:
            missing.append("writer")
        if not verifier:
            missing.append("verifier/verification")
        if not temporary:
            missing.append("temporary publication behavior")
        if not finalization:
            missing.append("finalization behavior")
        if not collision:
            missing.append("collision behavior")
        if missing:
            core.add(findings, "SIG-016", "HIGH", packet_id, packet_root / "artifacts",
                     "artifact contract missing explicit: " + ", ".join(missing), repo)


core.packet_manifest_paths = packet_manifest_paths
core.collect_types = collect_types
core.collect_error_codes = collect_error_codes
core.flatten_test_ids = flatten_test_ids
core.traceability_doc = traceability_doc
core.check_route_resolution = check_route_resolution
core.check_audit_closure = check_audit_closure
core.check_setting_registry = check_setting_registry
core.check_migrations = check_migrations
core.check_schema_policy = check_schema_policy
core.check_artifacts = check_artifacts

raise SystemExit(core.main())
