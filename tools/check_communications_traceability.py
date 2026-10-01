"""Validate implementation bindings; never infer certification from test names."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_GATES = frozenset({'LLD09-PFF-RELEASE-PIN', 'LLD09-GOLDEN-CORPUS-FREEZE'})


def validate(root=ROOT):
    ledger = json.loads((root / 'docs/implementation/lld09_traceability.json').read_text(encoding='utf8'))
    authority = json.loads((root / 'src/soma/communications/contracts/registry.json').read_text(encoding='utf8'))
    if ledger['design_sha'] != authority['design_sha']:
        raise ValueError('Communications bindings disagree with the pinned authority')
    expected = {case: scenario for suite in ('acceptance', 'failure-injection', 'privacy-security', 'adapter-compatibility')
        for case, scenario in authority['leaves'][f'tests/{suite}.json']['cases']}
    actual = {row['case_id']: row for row in ledger['cases']}
    if len(ledger['cases']) != 100 or len(actual) != 100 or set(actual) != set(expected):
        raise ValueError('Communications bindings must cover all 100 exact normative cases once')
    if {gate['id'] for gate in ledger['release_gates']} != RELEASE_GATES:
        raise ValueError('Communications native release gate identities changed')
    # This accepted implementation ledger has no native build/corpus certificate.
    # A future release must supply its owning LLD-12 freeze evidence, not flip a flag.
    if ledger['native_certified'] is not False or any(gate['status'] != 'deferred' for gate in ledger['release_gates']):
        raise ValueError('Native certification requires the deferred release freeze evidence')
    functions = {}
    for case, row in actual.items():
        if row['scenario'] != expected[case] or not row['implementation_owners'] or not row['executable_evidence']:
            raise ValueError(f'{case} lost its exact scenario or implementation evidence')
        for relative in row['implementation_owners']:
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(f'{case} references an unavailable implementation owner')
        for reference in row['executable_evidence']:
            relative, node = reference.split('::')
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(f'{case} references an unavailable test')
            if path not in functions:
                functions[path] = {n.name for n in ast.parse(path.read_text(encoding='utf8')).body if isinstance(n, ast.FunctionDef)}
            if node not in functions[path] or not node.startswith('test_'):
                raise ValueError(f'{case} references an unavailable executable test node')
        if '-C' in case and (set(row.get('release_gates', ())) != RELEASE_GATES
                or row['evidence_scope'] != 'synthetic_boundary_only_native_release_deferred'):
            raise ValueError(f'{case} must not be silently certified with synthetic evidence')
    return ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-native-certification', action='store_true')
    args = parser.parse_args()
    ledger = validate()
    print('Validated 100 exact Communications scenario bindings; this is structural traceability, not certification.')
    if args.require_native_certification:
        print('Native release certification blocked: ' + ', '.join(sorted(RELEASE_GATES)))
        return 2
    print('Native physical compatibility remains deferred under the accepted owner clarification.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
