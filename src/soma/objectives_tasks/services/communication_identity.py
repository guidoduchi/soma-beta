"""LLD-05 owns WFM and explicitly exported Objective communication identities."""
from __future__ import annotations

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4


class TaskObjectiveCommunicationIdentityProvider:
    @staticmethod
    def msg_draft_origin_fingerprint(reader, target_type, target_id, origin_command_id):
        """Read-only validity for a draft reporting an accepted completed review."""
        from soma.foundation.application.command_receipts import CommandReceiptStore
        from soma.foundation.strict_json import sha256_canonical_json
        from soma.objectives_tasks.repositories.objectives import ObjectiveProjectionRepository

        require_uuid4(target_id)
        require_uuid4(origin_command_id)
        if target_type != "OBJECTIVE":
            return None
        receipt = CommandReceiptStore().get(reader, origin_command_id)
        if receipt is None or receipt.command_type != "ReviewObjective" or receipt.target_id != target_id:
            return None
        identity = reader.connection.execute(
            "SELECT revision,creation_origin,superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (target_id,),
        ).fetchone()
        aggregate = ObjectiveProjectionRepository.aggregate(reader.connection, target_id)
        if (identity is None or identity[1] == "historical_provider_complete" or identity[2] is not None
                or aggregate is None or aggregate.execution_state != "reviewed" or aggregate.aggregate_outcome != "completed"):
            return None
        members = ObjectiveProjectionRepository._load_members(reader.connection, target_id)
        current = ObjectiveProjectionRepository._review_fingerprint(
            objective_id=target_id, objective_revision=identity[0], superseded_by=None, members=members,
        )
        review = ObjectiveProjectionRepository._current_review(reader.connection, target_id, current)
        if review is None or review["derived_outcome"] != "completed" or receipt.result_id != review["objective_review_event_id"]:
            return None
        return sha256_canonical_json({"schema": "OBJECTIVE_MSG_ORIGIN_V1", "objective_id": target_id,
            "origin_command_id": origin_command_id, "review_fingerprint": current,
            "aggregate_revision": aggregate.revision, "aggregate_fingerprint": aggregate.aggregate_input_fingerprint})

    @staticmethod
    def current_target_revision(reader, target_type, target_id):
        require_uuid4(target_id)
        if target_type == "WFM_TASK":
            sql = "SELECT t.revision FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id WHERE t.task_id=? AND t.task_kind='wfm'"
        elif target_type == "OBJECTIVE":
            sql = "SELECT revision FROM objectives WHERE objective_id=?"
        else:
            raise ValidationError("Task/Objective Communication target type is invalid")
        row = reader.connection.execute(sql, (target_id,)).fetchone()
        return None if row is None else row[0]

    @classmethod
    def lookup_trackable_identifier(cls, reader, exact_value):
        if not isinstance(exact_value, str) or not 1 <= len(exact_value) <= 512:
            raise ValidationError("Task/Objective Communication identifier is invalid")
        return cls._iter_trackable(reader, exact_value)

    @staticmethod
    def validate_target_revision(reader, target_type, target_id, revision):
        try:
            require_uuid4(target_id)
            if type(revision) is not int or revision < 1:
                return "INVALID"
            if target_type == "WFM_TASK":
                row = reader.connection.execute("SELECT t.revision FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id WHERE t.task_id=? AND t.task_kind='wfm'", (target_id,)).fetchone()
            elif target_type == "OBJECTIVE":
                row = reader.connection.execute("SELECT revision FROM objectives WHERE objective_id=?", (target_id,)).fetchone()
            else:
                return "INVALID"
            return "VALID" if row is not None and row[0] == revision else "INVALID"
        except ValidationError:
            return "INVALID"

    @staticmethod
    def snapshot_trackable_wfm_objective(reader):
        return TaskObjectiveCommunicationIdentityProvider._iter_trackable(reader)

    @classmethod
    def iter_target_identities(cls, reader, target_type, target_id):
        require_uuid4(target_id)
        if target_type not in {"WFM_TASK", "OBJECTIVE"}:
            raise ValidationError("Task/Objective Communication target type is invalid")
        return cls._iter_trackable(reader, target_type=target_type, target_id=target_id)

    @staticmethod
    def _iter_trackable(reader, exact_value=None, *, target_type=None, target_id=None):
        wfm_filter = "" if exact_value is None else " AND w.task_no=?"
        wfm_values = () if exact_value is None else (exact_value,)
        objective_filter = " WHERE 1" if exact_value is None else " WHERE tracking_id=?"
        objective_values = () if exact_value is None else (exact_value,)
        if target_type is not None:
            wfm_filter += " AND t.task_id=?" if target_type == "WFM_TASK" else " AND 0"
            wfm_values += (target_id,) if target_type == "WFM_TASK" else ()
            objective_filter += " AND objective_id=?" if target_type == "OBJECTIVE" else " AND 0"
            objective_values += (target_id,) if target_type == "OBJECTIVE" else ()
        for identity, number, revision in reader.connection.execute(
            "SELECT t.task_id,w.task_no,t.revision FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id "
            "WHERE t.task_kind='wfm'" + wfm_filter + " ORDER BY t.task_id", wfm_values,
        ):
            # Accepted WFM source authority exports scheduling, not external
            # creation. Neither local adoption nor plan start substitutes for it.
            yield {"target_type": "WFM_TASK", "target_id": require_uuid4(identity), "target_revision": revision,
                   "identity_kind": "WFM_OFFICIAL", "normalized_value": number,
                   "effective_from": {"known": False, "utc_epoch_seconds": None, "source_kind": "UNKNOWN"}}
        for identity, number, revision, created in reader.connection.execute(
            "SELECT objective_id,tracking_id,revision,created_at_utc FROM objectives" + objective_filter + " ORDER BY objective_id", objective_values,
        ):
            yield {"target_type": "OBJECTIVE", "target_id": require_uuid4(identity), "target_revision": revision,
                   "identity_kind": "OBJECTIVE_TRACKING", "normalized_value": number,
                   "effective_from": {"known": True, "utc_epoch_seconds": created, "source_kind": "OTHER_PROVIDER_TIME"}}

    @staticmethod
    def validate_trackable_target(uow, target_type, target_id, target_revision, matched_identity, *, identity_kind=None):
        try:
            require_uuid4(target_id)
            if type(target_revision) is not int or target_revision < 1:
                return "INVALID"
            if target_type == "WFM_TASK":
                if identity_kind is not None and identity_kind != "WFM_OFFICIAL":
                    return "INVALID"
                row = uow.connection.execute("SELECT w.task_no,t.revision FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id WHERE t.task_id=? AND t.task_kind='wfm'", (target_id,)).fetchone()
            elif target_type == "OBJECTIVE":
                if identity_kind is not None and identity_kind != "OBJECTIVE_TRACKING":
                    return "INVALID"
                row = uow.connection.execute("SELECT tracking_id,revision FROM objectives WHERE objective_id=?", (target_id,)).fetchone()
            else:
                return "INVALID"
            return "VALID" if row is not None and row[0] == matched_identity and row[1] == target_revision else "INVALID"
        except ValidationError:
            return "INVALID"
