from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from itertools import islice, zip_longest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import Chronology, TrackableIdentity
from soma.communications.contracts.message import TransientMessage
from soma.communications.domain.matching import _blocks_boundary
from soma.communications.repositories.sources import one


def _identity(row):
    return TrackableIdentity(row[1], row[2], row[3], row[4], row[0], Chronology(bool(row[5]), row[6], row[7]))


def _encoded(identity):
    return canonical_json_bytes([identity.target_type, identity.target_id, identity.target_revision,
        identity.identity_kind, identity.normalized_value, identity.effective_from.to_response()])


def _source_current(reader, job_id):
    row = one(reader, "SELECT j.source_scope_id,j.config_revision,s.revision AS current_revision "
        "FROM communication_job_scopes j JOIN communication_source_scopes s USING(source_scope_id) WHERE j.job_id=?", (job_id,))
    if row is None or row["config_revision"] != row["current_revision"]:
        raise SomaError("COMM_STALE", "Communication matching source configuration changed")


@dataclass(frozen=True, slots=True)
class MatchOccurrence:
    field: str
    offset: int
    identity: TrackableIdentity


class CommunicationMatchingService:
    """Bounded preparation of an immutable, encrypted owner-identity run index.

    Preparation writes derived identifiers in batches. Authoritative message
    commits still revalidate the complete current candidate set in their UoW.
    """

    def __init__(self, connection_factory, identity_providers, job_coordinator):
        self._factory = connection_factory
        self._identities = identity_providers
        self._jobs = job_coordinator

    def _authorize_preparation(self, writer, claim):
        self._jobs.assert_claim_current(writer, claim)
        _source_current(writer, claim.job_id)

    def prepare_run(self, claim):
        job_id = claim.job_id
        require_uuid4(job_id)
        with UnitOfWork(self._factory) as writer:
            self._authorize_preparation(writer, claim)
            run = one(writer, "SELECT * FROM communication_match_runs WHERE job_id=?", (job_id,))
            if run is not None and run["state"] == "READY":
                return run["registry_fingerprint"]
            if run is None:
                writer.connection.execute("INSERT INTO communication_match_runs(job_id,state) VALUES(?,'PREPARING')", (job_id,))
            else:
                # Only interrupted derived preparation is rebuilt. A sealed
                # snapshot remains the same throughout recovery of this job.
                writer.connection.execute("DELETE FROM communication_match_tokens WHERE job_id=?", (job_id,))
                writer.connection.execute("DELETE FROM communication_match_lengths WHERE job_id=?", (job_id,))
        digest = hashlib.sha256(b"SOMA_COMM_MATCH_REGISTRY_V1\x00")
        count = 0
        with ReadSnapshot(self._factory) as snapshot:
            _source_current(snapshot, job_id)
            identities = iter(self._identities.snapshot(snapshot))
            while batch := tuple(islice(identities, 250)):
                with UnitOfWork(self._factory) as writer:
                    self._authorize_preparation(writer, claim)
                    for identity in batch:
                        if not isinstance(identity, TrackableIdentity):
                            raise IntegrityFailure("Communication owner exported untyped matching identity")
                        encoded = _encoded(identity)
                        digest.update(len(encoded).to_bytes(8, "big"))
                        digest.update(encoded)
                        writer.connection.execute("INSERT INTO communication_match_tokens VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (job_id, identity.normalized_value, identity.target_type, identity.target_id, identity.target_revision,
                             identity.identity_kind, int(identity.effective_from.known), identity.effective_from.utc_epoch_seconds,
                             identity.effective_from.source_kind, count))
                        writer.connection.execute("INSERT OR IGNORE INTO communication_match_lengths VALUES(?,?,?)",
                            (job_id, identity.normalized_value[:8], len(identity.normalized_value)))
                        count += 1
            if not count:
                raise SomaError("COMM_NO_TRACKABLE_TARGETS", "No accepted operational identities are available")
            with UnitOfWork(self._factory) as writer:
                self._authorize_preparation(writer, claim)
                changed = writer.connection.execute("UPDATE communication_match_runs SET state='READY',registry_fingerprint=?,identity_count=? WHERE job_id=? AND state='PREPARING'",
                    (digest.hexdigest(), count, job_id))
                if changed.rowcount != 1:
                    raise IntegrityFailure("Communication matching preparation changed concurrently")
        return digest.hexdigest()

    @staticmethod
    def _ready(reader, job_id):
        require_uuid4(job_id)
        if one(reader, "SELECT 1 FROM communication_match_runs WHERE job_id=? AND state='READY'", (job_id,)) is None:
            raise IntegrityFailure("Communication matching snapshot is not sealed")

    @staticmethod
    def candidates(reader, job_id, token):
        for row in reader.connection.execute("SELECT token,target_type,target_id,target_revision,identity_kind,effective_known,effective_utc,effective_source "
            "FROM communication_match_tokens WHERE job_id=? AND token=? ORDER BY export_ordinal", (job_id, token)):
            yield _identity(row)

    def require_current_candidates(self, reader, job_id, token):
        self._ready(reader, job_id)
        # Both providers preserve their exported order. Comparing the entire
        # streams detects extra, missing, revised and reclassified candidates;
        # validating only the selected target would miss new ambiguity.
        absent = object()
        for old, current in zip_longest(self.candidates(reader, job_id, token), self._identities.lookup(reader, token), fillvalue=absent):
            if old != current:
                raise SomaError("COMM_TARGET_STALE", "Communication identifier candidate set changed")

    def inspect(self, reader, job_id, message):
        self._ready(reader, job_id)
        if not isinstance(message, TransientMessage):
            raise IntegrityFailure("Communication inspection requires a typed transient message")

        @lru_cache(maxsize=256)
        def lengths(prefixes):
            # At most 512 distinct lengths. Cache is local to one transient
            # message and contains prefixes/lengths only, never owner sets.
            values = reader.connection.execute("SELECT DISTINCT token_length FROM communication_match_lengths WHERE job_id=? AND prefix IN (" + ",".join("?" for _ in prefixes) + ")", (job_id, *prefixes))
            return tuple(row[0] for row in values)

        fields = (("subject", message.subject), ("body", message.body))
        attachments = ((f"attachment:{item.ordinal}", item.filename) for item in message.attachments)
        from itertools import chain
        for field, content in chain(fields, attachments):
            if not content:
                continue
            for start in range(len(content)):
                if start and _blocks_boundary(content[start - 1]):
                    continue
                prefixes = tuple(content[start:start + size] for size in range(1, min(8, len(content) - start) + 1))
                for size in lengths(prefixes):
                    end = start + size
                    if end > len(content) or (end < len(content) and _blocks_boundary(content[end])):
                        continue
                    for identity in self.candidates(reader, job_id, content[start:end]):
                        yield MatchOccurrence(field, start, identity)
