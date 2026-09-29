from __future__ import annotations

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.infrastructure.audit_registry import build_infrastructure_audit_registry
from soma.infrastructure.jobs import INFRASTRUCTURE_JOB_CONTRACTS
from soma.infrastructure.contracts.infrastructure import COMMANDS, REGISTRY, validate_request
from soma.reference.domain.matching import require_persisted_matching_profile
from soma.reference.queries.references import ReferenceQueries


class InfrastructureService:
    def __init__(self, connection_factory, *, site_dependencies=(), proof_provider=None,
                 device_reader=None, device_part_reader=None, consequence_reader=None,
                 setting_service=None, reference_queries=None, job_coordinator=None):
        self.factory = connection_factory
        self.site_dependencies = tuple(site_dependencies)
        self.proof_provider = proof_provider
        self.device_reader = device_reader
        self.device_part_reader = device_part_reader
        self.consequence_reader = consequence_reader
        self.setting_service = setting_service
        self.reference_queries = reference_queries or ReferenceQueries(connection_factory)
        self.job_coordinator = job_coordinator or DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(INFRASTRUCTURE_JOB_CONTRACTS),
        )
        self.boundary = CommandBoundary(connection_factory, AuditWriter(build_infrastructure_audit_registry()))

    def prepare(self, uow, command, payload, command_id, *, actor_kind="local_user", actor_id=None):
        from . import sites, placement, network_elements, relationships, components, regularization, workbooks
        for owner in (sites, placement, network_elements, relationships, components, regularization, workbooks):
            if command in owner.COMMAND_NAMES:
                if owner is workbooks:
                    return owner.prepare(self, uow, command, payload, command_id,
                                         actor_kind=actor_kind, actor_id=actor_id)
                return owner.prepare(self, uow, command, payload, command_id)
        from soma.foundation.errors import ValidationError
        raise ValidationError("Infrastructure command has no installed owner")

    def execute(self, command: str, *, command_id: str, payload: dict,
                actor_kind="local_user", actor_id=None):
        values = validate_request(command, payload)
        contract = COMMANDS[command]
        action = contract["audit_action"].split("@")[0]
        kind = next(target for name, target in REGISTRY["audit"]["actions"] if name == action)
        envelope = CommandEnvelope(command_id, command, kind, None, values)

        def prepare(uow):
            require_persisted_matching_profile(uow.connection)
            plan = self.prepare(uow, command, values, command_id,
                                actor_kind=actor_kind, actor_id=actor_id)
            if isinstance(plan, PreparedMutation):
                return plan
            def apply(inner):
                plan.apply(inner)
                payload = {"operation": command, "target_refs": [{"kind": plan.kind, "id": plan.identity}],
                           "base_revisions": {key: value for key, value in values.items()
                                              if key.endswith("revision")},
                           "result_refs": plan.result_refs}
                if values.get("reason_code"):
                    payload["reason_code"] = values["reason_code"]
                return AuditEventInput(
                    audit_event_id=new_uuid4(), action_type=action, action_version=1,
                    actor_kind=actor_kind, actor_id=actor_id, target_type=plan.kind,
                    target_id=plan.identity, command_id=command_id,
                    payload_schema="INFRA_AUDIT_PAYLOAD_V1", payload_version=1, payload=payload,
                    resulting_event_refs=tuple(AuditResultRef(ref["kind"], ref["id"]) for ref in plan.result_refs),
                )
            return PreparedMutation(
                no_change=plan.no_change, result_type=None if plan.no_change else plan.kind,
                result_id=None if plan.no_change else plan.identity,
                apply=None if plan.no_change else apply, response_schema="INFRA_MUTATION_RESULT_V1",
                response_factory=lambda inner: plan.response(),
            )
        return self.boundary.execute(envelope, prepare)
