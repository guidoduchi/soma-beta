from __future__ import annotations

import hashlib
from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import integer
from soma.communications.repositories.sources import one


def retention(reader, communication_id: str) -> dict:
    require_uuid4(communication_id)
    row = one(reader, "SELECT * FROM communication_retention WHERE communication_id=?", (communication_id,))
    if row is None:
        raise IntegrityFailure("Canonical communication has no retention authority")
    return row


def has_protected_dependency(reader, communication_id: str) -> bool:
    return bool(reader.connection.execute(
        "SELECT EXISTS(SELECT 1 FROM communication_links WHERE communication_id=? AND state='ACTIVE') "
        "OR EXISTS(SELECT 1 FROM communication_protection_holds WHERE communication_id=? AND state='ACTIVE') "
        "OR EXISTS(SELECT 1 FROM communication_proposals WHERE communication_id=? AND state IN ('PENDING','DEFERRED'))",
        (communication_id,) * 3,
    ).fetchone()[0])


def dependency_fingerprint(reader, communication_id: str) -> str:
    """Stream exact dependency authority only when recording a state transition."""
    digest = hashlib.sha256(b"SOMA_COMM_RETENTION_DEPENDENCIES_V1\x00")
    digest.update(communication_id.encode("ascii"))
    for kind, sql in (
        ("LINK", "SELECT communication_link_id,revision FROM communication_links WHERE communication_id=? AND state='ACTIVE' ORDER BY communication_link_id"),
        ("HOLD", "SELECT protection_hold_id,hold_kind,owner_ref,created_at_utc FROM communication_protection_holds WHERE communication_id=? AND state='ACTIVE' ORDER BY protection_hold_id"),
        ("PROPOSAL", "SELECT communication_proposal_id,revision,proposal_fingerprint FROM communication_proposals WHERE communication_id=? AND state IN ('PENDING','DEFERRED') ORDER BY communication_proposal_id"),
    ):
        for row in reader.connection.execute(sql, (communication_id,)):
            encoded = canonical_json_bytes([kind, *row])
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RetentionTransition:
    event_id: str
    from_state: str
    to_state: str
    new_revision: int


def record_transition(uow, row: dict, *, to_state: str, reason_code: str, dependency_event_id: str | None,
                      event_time: int, command_id: str, orphan_since: int | None, due: int | None) -> RetentionTransition:
    integer(event_time)
    require_uuid4(command_id)
    if dependency_event_id is not None:
        require_uuid4(dependency_event_id)
    event_id = new_uuid4()
    new_revision = row["revision"] + 1
    updated = uow.connection.execute(
        "UPDATE communication_retention SET state=?,orphan_since_utc=?,purge_due_utc=?,last_dependency_event_id=?,revision=?,updated_at_utc=? WHERE communication_id=? AND revision=?",
        (to_state, orphan_since, due, dependency_event_id, new_revision, event_time, row["communication_id"], row["revision"]),
    )
    if updated.rowcount != 1:
        raise IntegrityFailure("Communication retention revision changed before transition")
    uow.connection.execute(
        "INSERT INTO communication_retention_events(retention_event_id,communication_id,from_state,to_state,reason_code,dependency_fingerprint,recorded_at_utc,command_id,resulting_retention_revision) VALUES (?,?,?,?,?,?,?,?,?)",
        (event_id, row["communication_id"], row["state"], to_state, reason_code,
         dependency_fingerprint(uow, row["communication_id"]), event_time, command_id, new_revision),
    )
    return RetentionTransition(event_id, row["state"], to_state, new_revision)


def reconcile_retention(uow, communication_id: str, *, dependency_event_id: str, event_time: int,
                        grace_minutes: int, command_id: str) -> RetentionTransition | None:
    """Same-UoW participant after the caller has changed a link or governed hold.

    Pending intervals retain their accepted due time; a settings change does not
    restart grace. PURGED content needs the separate reconstruction contract.
    """
    integer(event_time)
    integer(grace_minutes, minimum=1, maximum=525600)
    row = retention(uow, communication_id)
    if row["state"] == "PURGED":
        return None
    protected = has_protected_dependency(uow, communication_id)
    if protected and row["state"] == "ORPHAN_PENDING_PURGE":
        return record_transition(uow, row, to_state="RETAINED", reason_code="PROTECTED_DEPENDENCY_RESTORED",
                                 dependency_event_id=dependency_event_id, event_time=event_time, command_id=command_id,
                                 orphan_since=None, due=None)
    if not protected and row["state"] == "RETAINED":
        due = integer(event_time + grace_minutes * 60)
        return record_transition(uow, row, to_state="ORPHAN_PENDING_PURGE", reason_code="FINAL_PROTECTED_DEPENDENCY_REMOVED",
                                 dependency_event_id=dependency_event_id, event_time=event_time, command_id=command_id,
                                 orphan_since=event_time, due=due)
    return None
