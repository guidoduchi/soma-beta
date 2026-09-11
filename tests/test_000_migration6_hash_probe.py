from __future__ import annotations

import hashlib
from pathlib import Path


def test_probe_candidate_migration_6_sha256() -> None:
    migration = Path(__file__).parents[1] / "src" / "soma" / "migrations" / "0006_objectives_tasks.sql"
    digest = hashlib.sha256(migration.read_bytes()).hexdigest()
    assert digest == "PROBE", f"candidate migration 6 sha256={digest}"
