from __future__ import annotations

import hashlib
from pathlib import Path


def test_migration6_digest_probe() -> None:
    migration = Path(__file__).parents[1] / "src" / "soma" / "migrations" / "0006_objectives_tasks.sql"
    digest = hashlib.sha256(migration.read_bytes()).hexdigest()
    raise AssertionError(f"MIGRATION6_SHA256={digest}")
