"""Capture only LLD-10's pinned normative leaves; never follow a branch head."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_SHA = '9a0e891127a771251afccca1a281b7ef7dde9e5f'
PACKET = 'spec/lld/ui-workbenches'


def capture():
    def read(path):
        return json.loads(subprocess.check_output(['git', 'show', f'{DESIGN_SHA}:{PACKET}/{path}'], cwd=ROOT))
    index = read('_index.json')
    return {'schema': 'SOMA_LLD10_PINNED_CONTRACTS_V1', 'design_sha': DESIGN_SHA,
            'packet_index': index, 'leaves': {path: read(path) for path in index['normative_paths']}}


if __name__ == '__main__':
    target = ROOT / 'src/soma/ui/registry.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(capture(), ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf8')
