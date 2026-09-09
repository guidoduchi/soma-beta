from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPO_ROOT / "src" / "soma"
_GENERIC_RESPONSE_SCHEMA = "CommandExecutionResultV1"


def _is_prepared_mutation_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == "PreparedMutation"
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == "PreparedMutation"
    return False


def _keyword_map(node: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}


def _explicit_response_schema(node: ast.Call, keywords: dict[str, ast.expr]) -> ast.expr | None:
    if "response_schema" in keywords:
        return keywords["response_schema"]
    # PreparedMutation positional fields:
    # no_change, result_type, result_id, apply, response_schema, response_version, response, response_factory
    if len(node.args) >= 5:
        return node.args[4]
    return None


def _has_exact_response(node: ast.Call, keywords: dict[str, ast.expr]) -> bool:
    if "response" in keywords or "response_factory" in keywords:
        return True
    # The seventh positional argument is response; the eighth is response_factory.
    return len(node.args) >= 7


def _is_generic_schema(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value == _GENERIC_RESPONSE_SCHEMA


def test_every_production_prepared_mutation_declares_exact_typed_response() -> None:
    offenders: list[str] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_prepared_mutation_call(node):
                continue
            keywords = _keyword_map(node)
            schema = _explicit_response_schema(node, keywords)
            problems: list[str] = []
            if schema is None:
                problems.append("missing explicit response_schema")
            elif _is_generic_schema(schema):
                problems.append("generic CommandExecutionResultV1 is forbidden")
            if not _has_exact_response(node, keywords):
                problems.append("missing explicit response/response_factory")
            if problems:
                offenders.append(f"{relative}:{node.lineno}: {', '.join(problems)}")

    assert not offenders, (
        "Every authoritative PreparedMutation must persist its declared typed response; "
        "generic/default replay snapshots are forbidden.\n" + "\n".join(offenders)
    )
