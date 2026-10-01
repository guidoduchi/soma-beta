from __future__ import annotations

from collections.abc import Iterator

from soma.foundation.errors import IntegrityFailure

from soma.communications.contracts.common import TARGET_TYPES, TrackableIdentity, integer, text
from soma.foundation.identifiers import require_uuid4
from soma.foundation.errors import ValidationError


class CommunicationIdentityProviders:
    """Consume one declared provider for each owning packet; never inspect owner tables."""

    def __init__(self, tickets, tasks_objectives, inventory):
        self._providers = ((tickets, "snapshot_trackable_sr_rfc", frozenset({"SERVICE_REQUEST", "RFC"})),
                           (tasks_objectives, "snapshot_trackable_wfm_objective", frozenset({"WFM_TASK", "OBJECTIVE"})),
                           (inventory, "snapshot_trackable_inventory", frozenset({"SPARE_REQUEST", "RMA", "FAULT_TAG"})))
        self._by_target = {target: provider for provider, _, targets in self._providers for target in targets}

    def snapshot(self, reader) -> Iterator[TrackableIdentity]:
        for provider, method, targets in self._providers:
            if provider is None or not callable(getattr(provider, method, None)):
                raise IntegrityFailure("A required Communication identity owner is unavailable")
            for raw in getattr(provider, method)(reader):
                value = raw if isinstance(raw, TrackableIdentity) else TrackableIdentity.from_value(raw)
                if value.target_type not in targets:
                    raise IntegrityFailure("Communication identity provider crossed its target ownership")
                yield value

    def validate(self, uow, identity: TrackableIdentity) -> str:
        provider = self._by_target[identity.target_type]
        if provider is None or not callable(getattr(provider, "validate_trackable_target", None)):
            return "INDETERMINATE"
        result = provider.validate_trackable_target(uow, identity.target_type, identity.target_id,
                                                    identity.target_revision, identity.normalized_value,
                                                    identity_kind=identity.identity_kind)
        if not isinstance(result, str) or result not in {"VALID", "INVALID", "INDETERMINATE"}:
            raise IntegrityFailure("Communication target owner returned an invalid disposition")
        return result

    def target_snapshot(self, reader, target_type, target_id):
        if not isinstance(target_type, str) or target_type not in TARGET_TYPES:
            raise ValidationError("Communication target type is invalid")
        require_uuid4(target_id)
        method = getattr(self._by_target[target_type], "iter_target_identities", None)
        if not callable(method):
            raise IntegrityFailure("Communication target identity owner is unavailable")
        for raw in method(reader, target_type, target_id):
            value = raw if isinstance(raw, TrackableIdentity) else TrackableIdentity.from_value(raw)
            if (value.target_type, value.target_id) != (target_type, target_id):
                raise IntegrityFailure("Communication owner crossed the requested target identity")
            yield value

    def sr_status_event(self, reader, sr_id, revision, event_id):
        method = getattr(self._by_target["SERVICE_REQUEST"], "accepted_sr_status_event", None)
        if not callable(method):
            raise IntegrityFailure("Communication SR status-evidence owner is unavailable")
        value = method(reader, sr_id, revision, event_id)
        if value is None:
            return None
        from soma.communications.contracts.common import closed
        item = closed(value, {"terminal", "recorded_at_utc", "command_id", "reviewed_correction", "current"})
        for name in ("terminal", "reviewed_correction", "current"):
            if type(item[name]) is not bool:
                raise IntegrityFailure("Communication SR owner returned invalid status evidence")
        integer(item["recorded_at_utc"])
        require_uuid4(item["command_id"])
        return item

    def validate_revision(self, reader, target_type, target_id, revision):
        if not isinstance(target_type, str) or target_type not in TARGET_TYPES:
            raise ValidationError("Communication target type is invalid")
        require_uuid4(target_id)
        integer(revision, minimum=1)
        provider = self._by_target.get(target_type)
        method = getattr(provider, "validate_target_revision", None)
        if not callable(method):
            return "INDETERMINATE"
        result = method(reader, target_type, target_id, revision)
        if not isinstance(result, str) or result not in {"VALID", "INVALID", "INDETERMINATE"}:
            raise IntegrityFailure("Communication target owner returned an invalid revision disposition")
        return result

    def validate_reassociation(self, reader, target_type, target_id, revision):
        current = self.validate_revision(reader, target_type, target_id, revision)
        if current != "VALID" or target_type not in {"SERVICE_REQUEST", "RFC"}:
            return current
        method = getattr(self._by_target[target_type], "validate_communication_reassociation", None)
        if not callable(method):
            return "INDETERMINATE"
        result = method(reader, target_type, target_id, revision)
        if not isinstance(result, str) or result not in {"VALID", "INVALID", "INDETERMINATE"}:
            raise IntegrityFailure("Communication owner returned invalid reassociation eligibility")
        return result

    def current_revision(self, reader, target_type, target_id):
        if not isinstance(target_type, str) or target_type not in TARGET_TYPES:
            raise ValidationError("Communication target type is invalid")
        require_uuid4(target_id)
        method = getattr(self._by_target[target_type], "current_target_revision", None)
        if not callable(method):
            raise IntegrityFailure("Communication target revision owner is unavailable")
        revision = method(reader, target_type, target_id)
        if revision is not None:
            integer(revision, minimum=1)
        return revision

    def msg_draft_origin(self, reader, origin_domain, target_type, target_id, origin_command_id):
        from soma.communications.contracts.common import fingerprint
        from soma.foundation.errors import SomaError
        if (origin_domain, target_type) not in {("LLD-05", "OBJECTIVE"), ("LLD-07", "SPARE_REQUEST")}:
            raise ValidationError("MSG draft origin is outside the current local draft flows")
        method = getattr(self._by_target[target_type], "msg_draft_origin_fingerprint", None)
        if not callable(method):
            raise SomaError("DEPENDENCY_INDETERMINATE", "MSG draft origin owner is unavailable")
        value = method(reader, target_type, target_id, origin_command_id)
        if value is None:
            raise SomaError("COMM_STALE", "MSG draft origin is no longer eligible")
        try:
            return fingerprint(value)
        except ValidationError:
            raise IntegrityFailure("MSG draft origin owner returned invalid evidence") from None

    def lookup(self, reader, exact_value):
        text(exact_value, minimum=1, maximum=512)
        for provider, _, targets in self._providers:
            method = getattr(provider, "lookup_trackable_identifier", None)
            if not callable(method):
                raise IntegrityFailure("Communication identifier lookup owner is unavailable")
            for raw in method(reader, exact_value):
                identity = raw if isinstance(raw, TrackableIdentity) else TrackableIdentity.from_value(raw)
                if identity.target_type not in targets or identity.normalized_value != exact_value:
                    raise IntegrityFailure("Communication owner lookup changed target ownership or exact identifier")
                yield identity

    def warehouse_receipt_target(self, reader, exact_sr7, exact_c10):
        """Consume Inventory's minimized item resolution without private reads."""
        from soma.communications.contracts.common import closed
        method = getattr(self._by_target["FAULT_TAG"], "resolve_warehouse_receipt_target", None)
        if not callable(method):
            raise IntegrityFailure("Communication warehouse target owner is unavailable")
        value = method(reader, exact_sr7, exact_c10)
        if value is None:
            return None
        try:
            item = closed(value, {"fault_tag_id", "fault_tag_revision", "membership_id", "membership_revision"})
            require_uuid4(item["fault_tag_id"])
            require_uuid4(item["membership_id"])
            integer(item["fault_tag_revision"], minimum=1)
            integer(item["membership_revision"], minimum=1)
        except ValidationError:
            raise IntegrityFailure("Communication warehouse target owner returned invalid evidence") from None
        return dict(item)
