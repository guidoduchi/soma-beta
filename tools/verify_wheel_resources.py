"""Verify built-wheel authority bytes against the pinned source contracts."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile


def verify(wheel_path: Path) -> None:
    from verify_ui_build import verify as verify_ui_build
    verify_ui_build()
    from soma.foundation.migrations.manifest import MigrationManifest
    from soma.reference.domain.matching import EXPECTED_ASSET_SHA256

    soma_source = Path(__file__).resolve().parents[1] / "src" / "soma"
    source = soma_source / "migrations"
    manifest = MigrationManifest.load(source)
    with ZipFile(wheel_path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError("wheel contains duplicate file entries")
        shipped_manifest = wheel.read("soma/migrations/manifest.json")
        if shipped_manifest != (source / "manifest.json").read_bytes():
            raise ValueError("wheel migration manifest differs from accepted source bytes")
        entries = json.loads(shipped_manifest)["migrations"]
        expected = {f"soma/migrations/{entry.filename}" for entry in manifest.entries}
        actual = {name for name in names if name.startswith("soma/migrations/") and name.endswith(".sql")}
        if actual != expected:
            raise ValueError("wheel migration file set differs from accepted manifest")
        for entry in entries:
            raw = wheel.read(f"soma/migrations/{entry['filename']}")
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("wheel migration hash differs from accepted manifest")
        unicode_bytes = wheel.read("soma/reference/assets/unicode_match_v1.json")
        if hashlib.sha256(unicode_bytes).hexdigest() != EXPECTED_ASSET_SHA256:
            raise ValueError("wheel Unicode asset hash differs from pinned authority")
        for resource in ("schema_manifest.json", "fk_index_exceptions.json"):
            shipped = wheel.read(f"soma/{resource}")
            if shipped != (soma_source / resource).read_bytes():
                raise ValueError(f"wheel {resource} differs from accepted source bytes")
        for packet in ("infrastructure", "communications"):
            registry = f"{packet}/contracts/registry.json"
            if wheel.read(f"soma/{registry}") != (soma_source / registry).read_bytes():
                raise ValueError(f"wheel {packet} registry differs from pinned source authority")
        ui_source = soma_source / 'ui'
        if wheel.read('soma/ui/registry.json') != (ui_source / 'registry.json').read_bytes():
            raise ValueError('wheel UI registry differs from pinned source authority')
        ui_manifest = (ui_source / 'static/manifest.json').read_bytes()
        if wheel.read('soma/ui/static/manifest.json') != ui_manifest:
            raise ValueError('wheel UI asset manifest differs from frozen build output')
        assets = json.loads(ui_manifest)['files']
        expected_assets = {'soma/ui/static/manifest.json', *('soma/ui/static/' + name for name in assets)}
        if {name for name in names if name.startswith('soma/ui/static/') and not name.endswith('/')} != expected_assets:
            raise ValueError('wheel UI asset set differs from frozen manifest')
        for name, entry in assets.items():
            raw = wheel.read('soma/ui/static/' + name)
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('wheel UI asset differs from frozen manifest')
    print(
        f"Verified {len(expected)} migration files, manifest, schema authority, "
        f"FK exceptions, packet registries, and pinned Unicode asset in {wheel_path.name}"
    )


if __name__ == "__main__":
    wheels = sorted(Path(sys.argv[1]).glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("expected exactly one built wheel")
    verify(wheels[0])
