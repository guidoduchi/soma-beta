from __future__ import annotations

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
            row = uow.connection.execute(
                "SELECT contract_name,contract_version,value_json,revision FROM setting_values WHERE setting_key=?",
                (setting_key,),
            ).fetchone()
            current: SettingValue | None = None
            if row is None:
                if base_revision is not None:
                    raise SomaError("STALE_REVISION", "setting no longer matches ABSENT precondition")
                prior_revision = None
                change_kind = "CREATE"
            else:
                current = self._parse_persisted(definition, row)
                assert current.revision is not None
                if base_revision is None or current.revision != base_revision:
                    raise SomaError("STALE_REVISION", "setting revision changed")
                if definition.semantic_equals(current.value, validated):
                    return PreparedMutation(
                        True,
                        None,
                        None,
                        response_schema="SettingValueV1",
                        response_version=1,
                        response=self._response_payload(definition, current.value, current.revision),
                    )
                prior_revision = current.revision
                change_kind = "UPDATE"
            if definition.state_validator is not None:
                definition.state_validator(uow.connection, validated)
            new_revision = 1 if prior_revision is None else prior_revision + 1
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if prior_revision is None:
                    inner.connection.execute(
                        "INSERT INTO setting_values(setting_key,contract_name,contract_version,value_json,revision,updated_at_utc,command_id) "
                        "VALUES (?, ?, ?, ?, 1, ?, ?)",
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
                    inner.connection.execute(
                        "UPDATE setting_values SET contract_name=?,contract_version=?,value_json=?,revision=revision+1,"
                        "updated_at_utc=?,command_id=? WHERE setting_key=?",
                        (
                            definition.contract_name,
                            definition.current_version,
                            value_json,
                            now,
                            command_id,
                            setting_key,
                        ),
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

            return PreparedMutation(
                False,
                "setting",
                setting_key,
                apply,
                response_schema="SettingValueV1",
                response_version=1,
                response=self._response_payload(definition, validated, new_revision),
            )

        return self._from_execution(self._boundary.execute(envelope, prepare))
