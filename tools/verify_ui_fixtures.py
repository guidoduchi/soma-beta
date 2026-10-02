"""Verify governed synthetic fixture context; this does not approve pixel baselines."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'src/web/fixtures/manifest.json'


def source_hash(path):
    return hashlib.sha256(path.read_text(encoding='utf8').replace('\r\n', '\n').encode('utf8')).hexdigest()


def validate(manifest):
    authority = json.loads((ROOT / 'src/soma/ui/registry.json').read_text(encoding='utf8'))['leaves']['ui/fixture-governance.json']
    required = set(authority['visual_fixture_manifest_required'])
    wanted = {(state, width) for state in authority['required_states'] for width in authority['representative_widths_css_px']}
    if manifest.get('schema') != 'SOMA_UI_SYNTHETIC_FIXTURES_V1' or manifest.get('class') != 'visual_acceptance_fixture':
        raise ValueError('Invalid fixture classification')
    provenance = manifest.get('source_sha256', {})
    if provenance != {name: source_hash(ROOT / 'src/web/fixtures' / name) for name in ('governed.html', 'governed.tsx')}:
        raise ValueError('Fixture source changed; review the semantic reason and update its version/provenance')
    seen, identities = set(), set()
    for item in manifest['fixtures']:
        if set(item) != required:
            raise ValueError('Fixture context fields differ from the owning contract')
        pair = (item['surface/state'], item['container_width_css_px'])
        if pair not in wanted or pair in seen or item['fixture_id'] in identities:
            raise ValueError('Missing, duplicate or unknown responsive fixture')
        seen.add(pair); identities.add(item['fixture_id'])
        if item['version'] != 1 or item['synthetic_or_irreversibly_sanitized_data_id'] != 'lld10-wholly-synthetic-v1':
            raise ValueError('Only the registered synthetic fixture set is permitted')
        if item['approval_state'] != 'semantic_review_pending_no_pixel_baseline':
            raise ValueError('No reviewed pixel baseline approval exists for this fixture version')
        if item['provenance'] != 'Test-only hand-authored synthetic values; no imported customer or mail data.':
            raise ValueError('Unknown fixture provenance')
        if item['skin_id'] != 'soma_core' or item['appearance_mode'] != 'light' or item['zoom_percent'] != 100 or item['text_scale'] != 1:
            raise ValueError('Unsupported fixture presentation context')
        if item['viewport_height_css_px'] != 900 or item['timezone'] != 'UTC' or item['deterministic_clock'] != '2026-10-01T00:00:00.000Z':
            raise ValueError('Non-deterministic fixture context')
        if item['reduced_motion'] is not True or item['forced_color_mode'] != 'none':
            raise ValueError('Unsupported fixture accessibility context')
        if item['platform/browser_host_profile'] != 'desktop-headless-chromium-version-recorded-at-execution':
            raise ValueError('Unknown browser fixture profile')
        if item['tolerance_profile'] != 'semantic-dom-primary-pixels-unapproved':
            raise ValueError('Unapproved rendering tolerance')
        if not item['mapped_requirement_or_test_ids'] or any(not re.fullmatch(r'LLD10-[TF]\d{3}', value) for value in item['mapped_requirement_or_test_ids']):
            raise ValueError('Invalid fixture traceability')
        # Reject obvious imported sensitive content in mutable metadata. This is
        # a defense in addition to the closed, hand-authored synthetic source set.
        text = json.dumps(item)
        if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:password|api[_-]?key|bearer)\s*[:=]|-----BEGIN .*PRIVATE KEY|(?:10|127)\.\d+\.\d+\.\d+', text, re.I):
            raise ValueError('Sensitive/private fixture metadata is forbidden')
        if not isinstance(item['expected_focus'], str) or not isinstance(item['expected_material_actions'], list):
            raise ValueError('Missing semantic fixture expectations')
    if seen != wanted:
        raise ValueError('Required responsive fixture coverage is incomplete')
    return len(seen)


if __name__ == '__main__':
    print(f'Validated {validate(json.loads(MANIFEST.read_text(encoding="utf8")))} synthetic fixture contexts; visual approval remains pending.')
