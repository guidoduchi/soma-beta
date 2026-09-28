from __future__ import annotations

from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.queries.data_instance_identity import DataInstanceIdentityReader


def test_identity_reader_returns_same_canonical_identity_in_snapshot_and_uow(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    with ReadSnapshot(factory) as snapshot:
        expected = DataInstanceIdentityReader.get(snapshot)
    with UnitOfWork(factory) as uow:
        assert DataInstanceIdentityReader.get(uow) == expected
