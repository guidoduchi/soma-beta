import importlib.util
from pathlib import Path


def test_exact_packet_bindings_do_not_promote_synthetic_tests_to_native_certification():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('communication_binding_check', root / 'tools/check_communications_traceability.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ledger = module.validate(root)
    assert len(ledger['cases']) == 100 and ledger['native_certified'] is False
    assert len([row for row in ledger['cases'] if row['evidence_scope'] == 'parser_independent_implementation']) == 88
