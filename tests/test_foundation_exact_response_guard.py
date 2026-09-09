from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPO_ROOT / "src" / "soma"
_GENERIC_RESPONSE_SCHEMA = "CommandExecutionResultV1"
_KNOWN_EXACT_RESPONSE_DEBT = Counter(
    {
        ("src/soma/tickets/rfc_hierarchy.py", "add_subordinate", "NO_CHANGE"): 1,
        ("src/soma/tickets/rfc_hierarchy.py", "add_subordinate", "MATERIAL"): 1,
    }
)


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


def _mutation_kind(node: ast.Call, keywords: dict[str, ast.expr]) -> str:
    value = keywords.get("no_change")
    if value is None and node.args:
        value = node.args[0]
    if isinstance(value, ast.Constant) and value.value is True:
        return "NO_CHANGE"
    if isinstance(value, ast.Constant) and value.value is False:
        return "MATERIAL"
    return "DYNAMIC"


class _PreparedMutationVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.function_stack: list[str] = []
        self.offenders: list[tuple[tuple[str, str, str], str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if _is_prepared_mutation_call(node):
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
                function_name = self.function_stack[-1] if self.function_stack else "<module>"
                key = (self.relative_path, function_name, _mutation_kind(node, keywords))
                self.offenders.append((key, f"{self.relative_path}:{node.lineno}: {', '.join(problems)}"))
        self.generic_visit(node)


def test_production_prepared_mutations_have_only_pinned_exact_response_debt() -> None:
    observed: Counter[tuple[str, str, str]] = Counter()
    details: list[str] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _PreparedMutationVisitor(relative)
        visitor.visit(tree)
        for key, detail in visitor.offenders:
            observed[key] += 1
            details.append(detail)

    unexpected = observed - _KNOWN_EXACT_RESPONSE_DEBT
    missing = _KNOWN_EXACT_RESPONSE_DEBT - observed
    assert not unexpected and not missing, (
        "PreparedMutation exact-response debt changed. New generic/default replay snapshots are forbidden, and the pinned "
        "RFC hierarchy debt must be removed from this baseline immediately when its RfcBranchV1 fingerprint contract is "
        "repaired.\n"
        f"unexpected={dict(unexpected)}\n"
        f"missing={dict(missing)}\n"
        + "\n".join(details)
    )
