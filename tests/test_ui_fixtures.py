"""F024/T052: reject sensitive metadata and incomplete/unreviewed fixture contexts."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_ui_fixtures', ROOT / 'tools/verify_ui_fixtures.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_manifest():
    return json.loads(module.MANIFEST.read_text(encoding='utf8'))


def test_all_required_states_have_separately_rendered_exact_contexts():
    assert module.validate(fixture_manifest()) == 36


@pytest.mark.parametrize('canary', ['private.person@example.com', 'password=synthetic-canary',
    'api_key=synthetic-canary', 'Bearer: synthetic-canary', '-----BEGIN RSA PRIVATE KEY-----', '10.20.30.40'])
def test_sensitive_fixture_metadata_is_rejected(canary):
    value = fixture_manifest()
    value['fixtures'][0]['expected_focus'] = canary
    with pytest.raises(ValueError, match='Sensitive/private'):
        module.validate(value)


@pytest.mark.parametrize('mutation', ['missing_context', 'missing_width', 'duplicate_state', 'invented_approval', 'changed_source'])
def test_context_and_baseline_governance_fail_closed(mutation):
    value = fixture_manifest()
    if mutation == 'missing_context': del value['fixtures'][0]['timezone']
    if mutation == 'missing_width': value['fixtures'].pop()
    if mutation == 'duplicate_state': value['fixtures'][-1] = copy.deepcopy(value['fixtures'][0])
    if mutation == 'invented_approval': value['fixtures'][0]['approval_state'] = 'approved'
    if mutation == 'changed_source': value['source_sha256']['governed.tsx'] = '0' * 64
    with pytest.raises(ValueError): module.validate(value)
