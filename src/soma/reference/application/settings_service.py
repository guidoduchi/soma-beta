from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes, loads_strict
from soma.reference.audit_registry import build_reference_audit_registry
from soma.reference.domain.settings import SettingDefinition, SettingDefinitionRegistry

SettingSource = Literal["DEFAULT", "PERSISTED"]


@dataclass(frozen=True, slots=True)
class SettingValue:
    setting_key: str
    contract_name: str
    contract_version: int
    value: Any
    revision: int | None
    source: SettingSource
    semantic_owner: str
    replayed: bool = False
    no_change: bool = False


@dataclass(frozen=True, slots=True)
class SettingWriteParticipant:
    setting_key: str
    contract_name: str
    contract_version: int
    semantic_owner: str
    value: Any
    prior_revision: int | None
    new_revision: int
    change_kind: Literal["CREATE", "UPDATE"] | None
    no_change: bool
    _apply: Callable[[UnitOfWork], AuditEventInput] | None

    def response_payload(self) -> dict[str, Any]:
        return {
            "setting_key": self.setting_key,
            "value": self.value,
            "source": "PERSISTED",
            "revision": self.new_revision,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "semantic_owner": self.semantic_owner,
        }

    def apply(self, uow: UnitOfWork) -> AuditEventInput:
        if self.no_change or self._apply is None:
            raise IntegrityFailure("NO_CHANGE setting participant has no material apply")
        return self._apply(uow)


class SettingService:
    def __init__(self, connection_factory: ConnectionFactory, registry: SettingDefinitionRegistry) -> None:
        self._factory = connection_factory
        self._registry = registry
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_reference_audit_registry()),
        )

    @staticmethod
    def _parse_persisted(definition: SettingDefinition, row: Any) -> SettingValue:
        contract_name = str(row[0])
        version = int(row[1])
        if contract_name != definition.contract_name or version != definition.current_version:
            raise SomaError(
                "SETTING_CONTRACT_MISMATCH",
                "persisted setting contract/version is not supported by the registered definition",
            )
        raw = str(row[2])
        try:
            parsed = loads_strict(raw, max_bytes=definition.max_utf8_bytes)
            value = definition.validate_value(parsed)
        except SomaError:
            raise
        except Exception as exc:
            raise SomaError("SETTING_CONTRACT_MISMATCH", "persisted setting value cannot be interpreted") from exc
        return SettingValue(
            definition.setting_key,
            contract_name,
            version,
            value,
            int(row[3]),
            "PERSISTED",
            definition.semantic_owner,
        )

    @staticmethod
    def _response_payload(definition: SettingDefinition, value: Any, revision: int) -> dict[str, Any]:
        return {
            "setting_key": definition.setting_key,
            "value": value,
            "source": "PERSISTED",
            "revision": revision,
            "contract_name": definition.contract_name,
            "contract_version": definition.current_version,
            "semantic_owner": definition.semantic_owner,
        }

    @staticmethod
    def _from_execution(execution: CommandExecutionResult) -> SettingValue:
        if execution.response_schema != "SettingValueV1" or execution.response_version != 1:
            raise IntegrityFailure("setting replay result schema/version is invalid")
        payload = execution.response
        required = {
            "setting_key",
            "value",
            "source",
            "revision",
            "contract_name",
            "contract_version",
            "semantic_owner",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise IntegrityFailure("setting replay result payload is invalid")
        setting_key = payload["setting_key"]
        source = payload["source"]
        revision = payload["revision"]
        contract_name = payload["contract_name"]
        contract_version = payload["contract_version"]
        semantic_owner = payload["semantic_owner"]
        if not isinstance(setting_key, str) or not setting_key:
            raise IntegrityFailure("setting replay result key is invalid")
        if source != "PERSISTED":
            raise IntegrityFailure("setting mutation replay result source is invalid")
        if type(revision) is not int or revision <= 0:
            raise IntegrityFailure("setting replay result revision is invalid")
        if not isinstance(contract_name, str) or not contract_name:
            raise IntegrityFailure("setting replay result contract name is invalid")
        if type(contract_version) is not int or contract_version <= 0:
            raise IntegrityFailure("setting replay result contract version is invalid")
        if not isinstance(semantic_owner, str) or not semantic_owner:
            raise IntegrityFailure("setting replay result semantic owner is invalid")
        return SettingValue(
            setting_key=setting_key,
            contract_name=contract_name,
            contract_version=contract_version,
            value=payload["value"],
            revision=revision,
            source="PERSISTED",
            semantic_owner=semantic_owner,
            replayed=execution.replayed,
            no_change=execution.no_change,
        )

    def get(self, setting_key: str) -> SettingValue:
        definition = self._registry.require(setting_key)
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT contract_name,contract_version,value_json,revision FROM setting_values WHERE setting_key=?",
                (setting_key,),
            ).fetchone()
        if row is None:
            default = definition.validate_value(definition.default_provider())
            return SettingValue(
                setting_key,
                definition.contract_name,
                definition.current_version,
                default,
                None,
                "DEFAULT",
                definition.semantic_owner,
            )
        return self._parse_persisted(definition, row)

    def list_for_owner(self, owner: str) -> tuple[SettingValue, ...]:
        return tuple(self.get(definition.setting_key) for definition in self._registry.all_for_owner(owner))

    def prepare_write_participant(
        self,
        uow: UnitOfWork,
        *,
        command_id: str,
        setting_key: str,
        base_revision: int | None,
        value: Any,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> SettingWriteParticipant:
        definition = self._registry.require(setting_key)
        validated = definition.validate_value(value)
        value_json = canonical_json_bytes(validated).decode("utf-8")
        row = uow.connection.execute(
            "SELECT contract_name,contract_version,value_json,revision "
            "FROM setting_values WHERE setting_key=?",
            (setting_key,),
        ).fetchone()
        if row is None:
            if base_revision is not None:
                raise SomaError(
                    "STALE_REVISION",
                    "setting no longer matches ABSENT precondition",
                )
            prior_revision = None
            new_revision = 1
            change_kind: Literal["CREATE", "UPDATE"] | None = "CREATE"
        else:
            current = self._parse_persisted(definition, row)
            assert current.revision is not None
            if base_revision is None or current.revision != base_revision:
                raise SomaError("STALE_REVISION", "setting revision changed")
            if definition.semantic_equals(current.value, validated):
                return SettingWriteParticipant(
                    setting_key=definition.setting_key,
                    contract_name=definition.contract_name,
                    contract_version=definition.current_version,
                    semantic_owner=definition.semantic_owner,
                    value=current.value,
                    prior_revision=current.revision,
                    new_revision=current.revision,
                    change_kind=None,
                    no_change=True,
                    _apply=None,
                )
            prior_revision = current.revision
            new_revision = prior_revision + 1
            change_kind = "UPDATE"
        if definition.state_validator is not None:
            definition.state_validator(uow.connection, validated)
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()

        def apply(inner: UnitOfWork) -> AuditEventInput:
            if prior_revision is None:
                inner.connection.execute(
                    "INSERT INTO setting_values("
                    "setting_key,contract_name,contract_version,value_json,revision,"
                    "updated_at_utc,command_id"
                    ") VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (
                        setting_key,
                        definition.contract_name,
                        definition.current_version,
                        value_json,
                        now,
                        command_id,
                    ),
                )
            else:
                changed = inner.connection.execute(
                    "UPDATE setting_values SET contract_name=?,contract_version=?,"
                    "value_json=?,revision=revision+1,updated_at_utc=?,command_id=? "
                    "WHERE setting_key=? AND revision=?",
                    (
                        definition.contract_name,
                        definition.current_version,
                        value_json,
                        now,
                        command_id,
                        setting_key,
                        prior_revision,
                    ),
                )
                if changed.rowcount != 1:
                    raise IntegrityFailure(
                        "setting revision changed during same-UoW participant apply"
                    )
            return AuditEventInput(
                audit_event_id=audit_event_id,
                action_type="setting.written",
                action_version=1,
                actor_kind=actor_kind,
                actor_id=actor_id,
                target_type="setting",
                target_id=setting_key,
                command_id=command_id,
                payload_schema="SettingWriteAuditV1",
                payload_version=1,
                payload={
                    "setting_key": setting_key,
                    "contract_id": definition.contract_name,
                    "contract_version": definition.current_version,
                    "prior_revision": prior_revision,
                    "new_revision": new_revision,
                    "change_kind": change_kind,
                },
                resulting_event_refs=(AuditResultRef("setting", setting_key),),
            )

        return SettingWriteParticipant(
            setting_key=definition.setting_key,
            contract_name=definition.contract_name,
            contract_version=definition.current_version,
            semantic_owner=definition.semantic_owner,
            value=validated,
            prior_revision=prior_revision,
            new_revision=new_revision,
            change_kind=change_kind,
            no_change=False,
            _apply=apply,
        )

    def write(
        self,
        *,
        command_id: str,
        setting_key: str,
        base_revision: int | None,
        value: Any,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> SettingValue:
        definition = self._registry.require(setting_key)
        validated = definition.validate_value(value)
        value_json = canonical_json_bytes(validated).decode("utf-8")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="WriteSetting",
            target_type="setting",
            target_id=setting_key,
            semantic_payload={
                "setting_key": setting_key,
                "contract_name": definition.contract_name,
                "contract_version": definition.current_version,
                "value": validated,
            },
            base_revisions={} if base_revision is None else {"setting": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            participant = self.prepare_write_participant(
                uow,
                command_id=command_id,
                setting_key=setting_key,
                base_revision=base_revision,
                value=validated,
                actor_kind=actor_kind,
                actor_id=actor_id,
            )
            if participant.no_change:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="SettingValueV1",
                    response_version=1,
                    response=participant.response_payload(),
                )
            return PreparedMutation(
                False,
                "setting",
                setting_key,
                participant.apply,
                response_schema="SettingValueV1",
                response_version=1,
                response=participant.response_payload(),
            )

        return self._from_execution(self._boundary.execute(envelope, prepare))
