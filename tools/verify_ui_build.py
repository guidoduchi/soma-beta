"""Check frozen browser output and its source inputs without running Node."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    from build_ui_asset_manifest import source_inputs
    static = ROOT / 'src/soma/ui/static'
    manifest = json.loads((static / 'manifest.json').read_text(encoding='utf8'))
    if manifest.get('source_input_format') != 'utf8-lf' or source_inputs() != manifest['source_sha256']:
        raise ValueError('Browser sources changed after their frozen build; rebuild the UI')
    actual = {path.relative_to(static).as_posix() for path in static.rglob('*') if path.is_file()}
    if actual != {'manifest.json', *manifest['files']}:
        raise ValueError('Browser asset set differs from its frozen manifest')
    for name, entry in manifest['files'].items():
        raw = (static / name).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Browser asset differs from its frozen manifest')


if __name__ == '__main__':
    verify()
    print('Verified frozen browser assets against their exact source inputs')
