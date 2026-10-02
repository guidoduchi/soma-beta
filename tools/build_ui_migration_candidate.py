"""Build the centrally allocated LLD-10 candidate; accepted history is immutable."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_SHA = '9a0e891127a771251afccca1a281b7ef7dde9e5f'


def render():
    allocation = json.loads(subprocess.check_output(['git', 'show', f'{DESIGN_SHA}:spec/lld/migrations.json'], cwd=ROOT))
    entry = next(item for item in allocation['allocations'] if item['packet_id'] == 'LLD-10')
    assert (entry['sequence'], entry['filename']) == (17, '0017_ui_workbenches.sql')
    registry = json.loads((ROOT / 'src/soma/ui/registry.json').read_text(encoding='utf8'))
    schema = registry['leaves']['schema/working-copy.json']
    columns = schema['tables'][0]['columns'] + [
        'CHECK(expires_at_utc=updated_at_utc+604800)',
        'CHECK(json_valid(payload_json) AND json_type(payload_json)=\'object\')',
        'CHECK(json_valid(dirty_paths_json) AND json_type(dirty_paths_json)=\'array\')',
        'CHECK(length(CAST(payload_json AS BLOB))<=262144)',
        'CHECK(content_hash NOT GLOB \'*[^0-9a-f]*\')']
    statements = ['-- LLD-10; central allocation 17 supersedes provisional packet-local sequence 16.',
        'CREATE TABLE ui_working_copies(\n    ' + ',\n    '.join(columns) + '\n) STRICT;']
    statements += [sql + ';' for sql in schema['indexes']]
    # LLD-01 mandates index coverage on every child FK; the unique recovery key
    # already covers owner_profile_id. These support the two receipt references.
    statements += ['CREATE INDEX idx_ui_working_copy_created_command ON ui_working_copies(created_command_id);',
        'CREATE INDEX idx_ui_working_copy_checkpoint_command ON ui_working_copies(last_checkpoint_command_id);']
    return '\n\n'.join(statements) + '\n'


if __name__ == '__main__':
    manifest = json.loads((ROOT / 'src/soma/migrations/manifest.json').read_text(encoding='utf8'))
    if any(row['sequence'] >= 17 for row in manifest['migrations']):
        raise SystemExit('Refusing to rewrite an accepted runtime migration')
    (ROOT / 'docs/implementation/lld10_migration17_candidate.sql').write_text(render(), encoding='utf8', newline='\n')
