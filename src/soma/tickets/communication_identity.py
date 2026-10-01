"""LLD-03 read/validation provider for the LLD-09 closed identity contract."""
from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4

from .sr_source_projection import _TERMINAL_SR_STATUSES
from .validation import validate_official_sr_no, validate_rfc_no


def _chronology(instant):
    if instant is None:
        return {"known": False, "utc_epoch_seconds": None, "source_kind": "UNKNOWN"}
    if type(instant) is not int or instant < 0:
        raise IntegrityFailure("Ticket communication chronology is invalid")
    return {"known": True, "utc_epoch_seconds": instant, "source_kind": "OTHER_PROVIDER_TIME"}


class TicketCommunicationIdentityProvider:
    @classmethod
    def accepted_sr_status_event(cls, reader, sr_id, sr_revision, event_id):
        """Exact accepted owner evidence; external chronology is not grace time."""
        require_uuid4(event_id)
        if cls.validate_target_revision(reader, "SERVICE_REQUEST", sr_id, sr_revision) != "VALID":
            return None
        row = reader.connection.execute(
            "SELECT o.text_value,o.recorded_at_utc,o.accepted_command_id,o.precedence_basis,"
            "p.status_observation_id=o.sr_source_field_observation_id "
            "FROM sr_source_field_observations o JOIN sr_current_source_projection p USING(service_request_id) "
            "WHERE o.sr_source_field_observation_id=? AND o.service_request_id=? "
            "AND o.field_key='status' AND o.value_state='usable' AND o.value_kind='controlled'", (event_id, sr_id),
        ).fetchone()
        if row is None:
            return None
        return {"terminal": row[0] in _TERMINAL_SR_STATUSES, "recorded_at_utc": row[1], "command_id": row[2],
            "reviewed_correction": row[3] == "reviewed_correction", "current": bool(row[4])}

    @staticmethod
    def current_target_revision(reader, target_type, target_id):
        require_uuid4(target_id)
        if target_type == "SERVICE_REQUEST":
            sql = "SELECT revision FROM service_requests WHERE service_request_id=? AND official_sr_no IS NOT NULL"
        elif target_type == "RFC":
            sql = "SELECT revision FROM rfcs WHERE rfc_id=?"
        else:
            raise ValidationError("Ticket Communication target type is invalid")
        row = reader.connection.execute(sql, (target_id,)).fetchone()
        return None if row is None else row[0]

    @classmethod
    def lookup_trackable_identifier(cls, reader, exact_value):
        if not isinstance(exact_value, str) or not 1 <= len(exact_value) <= 512:
            raise ValidationError("Ticket Communication identifier is invalid")
        return cls._iter_trackable(reader, exact_value)

    @classmethod
    def validate_communication_reassociation(cls, reader, target_type, target_id, revision):
        if cls.validate_target_revision(reader, target_type, target_id, revision) != "VALID":
            return "INVALID"
        if target_type == "SERVICE_REQUEST":
            row = reader.connection.execute(
                "SELECT o.text_value FROM sr_current_source_projection p "
                "LEFT JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.status_observation_id "
                "AND o.service_request_id=p.service_request_id AND o.field_key='status' AND o.value_state='usable' "
                "WHERE p.service_request_id=?", (target_id,)).fetchone()
            # A manual SR with no accepted provider status has no terminal
            # consequence. The owner guards reviewed status reversal.
            return "INVALID" if row is not None and row[0] in _TERMINAL_SR_STATUSES else "VALID"
        if target_type == "RFC":
            governed = reader.connection.execute(
                "SELECT 1 FROM rfc_terminal_cascade_rfc_members m "
                "JOIN rfc_terminal_cascade_proposals p ON p.rfc_terminal_cascade_proposal_id=m.rfc_terminal_cascade_proposal_id "
                "JOIN rfc_current_source_projection s ON s.rfc_id=p.trigger_rfc_id AND s.terminal_epoch_id=p.terminal_epoch_id "
                "WHERE m.rfc_id=? AND p.proposal_state='executed' LIMIT 1", (target_id,)).fetchone()
            # Pending/provider terminal evidence is not an applied local
            # Communications consequence. Reviewed reversal clears its epoch.
            return "INVALID" if governed is not None else "VALID"
        return "INVALID"

    @staticmethod
    def validate_target_revision(reader, target_type, target_id, revision):
        try:
            require_uuid4(target_id)
            if type(revision) is not int or revision < 1:
                return "INVALID"
            if target_type == "SERVICE_REQUEST":
                row = reader.connection.execute("SELECT revision FROM service_requests WHERE service_request_id=? AND official_sr_no IS NOT NULL", (target_id,)).fetchone()
            elif target_type == "RFC":
                row = reader.connection.execute("SELECT revision FROM rfcs WHERE rfc_id=?", (target_id,)).fetchone()
            else:
                return "INVALID"
            return "VALID" if row is not None and row[0] == revision else "INVALID"
        except ValidationError:
            return "INVALID"

    @staticmethod
    def snapshot_trackable_sr_rfc(reader):
        return TicketCommunicationIdentityProvider._iter_trackable(reader)

    @classmethod
    def iter_target_identities(cls, reader, target_type, target_id):
        require_uuid4(target_id)
        if target_type not in {"SERVICE_REQUEST", "RFC"}:
            raise ValidationError("Ticket Communication target type is invalid")
        return cls._iter_trackable(reader, target_type=target_type, target_id=target_id)

    @staticmethod
    def _iter_trackable(reader, exact_value=None, *, target_type=None, target_id=None):
        sr_filter = "" if exact_value is None else " AND (s.official_sr_no=? OR s.local_sr_no=?)"
        sr_values = () if exact_value is None else (exact_value, exact_value)
        if target_type is not None:
            sr_filter += " AND s.service_request_id=?" if target_type == "SERVICE_REQUEST" else " AND 0"
            sr_values += (target_id,) if target_type == "SERVICE_REQUEST" else ()
        # An unpromoted local SR has no accepted official communication target.
        for identity, official, alias, revision, instant in reader.connection.execute(
            "SELECT s.service_request_id,s.official_sr_no,s.local_sr_no,s.revision,o.integer_value "
            "FROM service_requests s LEFT JOIN sr_current_source_projection p ON p.service_request_id=s.service_request_id "
            "LEFT JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.report_date_observation_id "
            "AND o.service_request_id=s.service_request_id AND o.field_key='report_date' AND o.value_state='usable' "
            "WHERE s.official_sr_no IS NOT NULL" + sr_filter + " ORDER BY s.service_request_id", sr_values,
        ):
            common = {"target_type": "SERVICE_REQUEST", "target_id": require_uuid4(identity), "target_revision": revision,
                      "effective_from": _chronology(instant)}
            if exact_value is None or official == exact_value:
                yield common | {"identity_kind": "SERVICE_REQUEST_OFFICIAL", "normalized_value": validate_official_sr_no(official)}
            if alias is not None and (exact_value is None or alias == exact_value):
                yield common | {"identity_kind": "SERVICE_REQUEST_LOCAL_ALIAS", "normalized_value": alias}
        rfc_filter = " WHERE 1" if exact_value is None else " WHERE r.rfc_no=?"
        rfc_values = () if exact_value is None else (exact_value,)
        if target_type is not None:
            rfc_filter += " AND r.rfc_id=?" if target_type == "RFC" else " AND 0"
            rfc_values += (target_id,) if target_type == "RFC" else ()
        for identity, number, revision, instant in reader.connection.execute(
            "SELECT r.rfc_id,r.rfc_no,r.revision,p.external_created_at_utc FROM rfcs r "
            "LEFT JOIN rfc_current_source_projection p ON p.rfc_id=r.rfc_id" + rfc_filter + " ORDER BY r.rfc_id", rfc_values,
        ):
            yield {"target_type": "RFC", "target_id": require_uuid4(identity), "target_revision": revision,
                   "identity_kind": "RFC_OFFICIAL", "normalized_value": validate_rfc_no(number), "effective_from": _chronology(instant)}

    @staticmethod
    def validate_trackable_target(uow, target_type, target_id, target_revision, matched_identity, *, identity_kind=None):
        try:
            require_uuid4(target_id)
            if type(target_revision) is not int or target_revision < 1:
                return "INVALID"
            if target_type == "SERVICE_REQUEST":
                row = uow.connection.execute("SELECT official_sr_no,local_sr_no,revision FROM service_requests WHERE service_request_id=?", (target_id,)).fetchone()
                if row is None or row[0] is None or row[2] != target_revision:
                    return "INVALID"
                if identity_kind is not None:
                    expected = {"SERVICE_REQUEST_OFFICIAL": row[0], "SERVICE_REQUEST_LOCAL_ALIAS": row[1]}.get(identity_kind)
                    return "VALID" if expected is not None and expected == matched_identity else "INVALID"
                return "VALID" if matched_identity in (row[0], row[1]) else "INVALID"
            if target_type == "RFC":
                if identity_kind is not None and identity_kind != "RFC_OFFICIAL":
                    return "INVALID"
                row = uow.connection.execute("SELECT rfc_no,revision FROM rfcs WHERE rfc_id=?", (target_id,)).fetchone()
                return "VALID" if row is not None and row[0] == matched_identity and row[1] == target_revision else "INVALID"
            return "INVALID"
        except ValidationError:
            return "INVALID"

    @staticmethod
    def current_terminal_state(reader, target_type, target_id):
        require_uuid4(target_id)
        if target_type == "SERVICE_REQUEST":
            row = reader.connection.execute(
                "SELECT o.text_value FROM service_requests s LEFT JOIN sr_current_source_projection p ON p.service_request_id=s.service_request_id "
                "LEFT JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.status_observation_id AND o.service_request_id=s.service_request_id "
                "WHERE s.service_request_id=?", (target_id,)).fetchone()
            if row is None or row[0] is None:
                return "UNKNOWN"
            return "TERMINAL" if row[0] in _TERMINAL_SR_STATUSES else "ACTIVE"
        if target_type == "RFC":
            row = reader.connection.execute("SELECT status_class FROM rfc_current_source_projection WHERE rfc_id=?", (target_id,)).fetchone()
            if row is None or row[0] == "unknown":
                return "UNKNOWN"
            return "TERMINAL" if row[0] in {"terminal_closed", "terminal_cancelled"} else "ACTIVE"
        return "UNKNOWN"
