from __future__ import annotations

import ast
import inspect

import soma.ticket_import.commands.publish_staged_run as publish_module


def _class_node() -> ast.ClassDef:
    tree = ast.parse(inspect.getsource(publish_module))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PublishStagedImportRunService"
    )


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_proposal_calculation_is_confined_to_read_snapshot_preflight() -> None:
    service = _class_node()
    preflight = _method(service, "_preflight_publication")

    proposal_calls: list[str] = []
    for method in (node for node in service.body if isinstance(node, ast.FunctionDef)):
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"_advanced_search_proposal_writes", "_wfm_proposal_writes"}
            ):
                proposal_calls.append((method.name, node.func.attr))

    assert proposal_calls == [
        ("_preflight_publication", "_advanced_search_proposal_writes"),
        ("_preflight_publication", "_wfm_proposal_writes"),
    ]
    assert any(
        isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "ReadSnapshot"
            for item in node.items
        )
        for node in ast.walk(preflight)
    )


def test_writer_keeps_authoritative_fingerprint_reverification_without_proposal_rebuild() -> None:
    service = _class_node()
    publish = _method(service, "publish")
    nested_prepare = next(
        node
        for node in publish.body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare"
    )

    calls = {
        node.func.id
        for node in ast.walk(nested_prepare)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attribute_calls = {
        node.func.attr
        for node in ast.walk(nested_prepare)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "verify_staged_logical_run" in calls
    assert "assert_claim_current" in attribute_calls
    assert "_advanced_search_proposal_writes" not in attribute_calls
    assert "_wfm_proposal_writes" not in attribute_calls
    assert "_wfm_reconciliation_findings" in attribute_calls
