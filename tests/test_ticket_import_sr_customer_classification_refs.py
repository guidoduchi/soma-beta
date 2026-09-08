from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService

from test_ticket_import_sr_customer_acceptance import (
    FakeClassificationParticipant,
    _customer,
    _factory,
    _official_sr,
    _seed_customer_proposal,
)


class ClassificationParticipantWithResultRef(FakeClassificationParticipant):
    def __init__(self) -> None:
        super().__init__()
        self.classification_event_id = new_uuid4()

    def apply_customer_change(self, uow, sr_id: str, new_customer_org_id: str | None, command_context):
        super().apply_customer_change(uow, sr_id, new_customer_org_id, command_context)
        return (("sr_classification_event", self.classification_event_id),)


def test_customer_reconciliation_propagates_lld06_result_refs_to_orchestration(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _customer(factory, name="Classification Ref Target", account_code="CR-200")
    sr = _official_sr(factory, "33445566")
    seeded = _seed_customer_proposal(
        factory,
        sr_id=sr.service_request_id,
        sr_no="33445566",
        target_customer_org_id=target.customer_org_id,
        prior_customer_org_id=None,
        account_code="CR-200",
        customer_label="Classification Ref Target",
    )
    participant = ClassificationParticipantWithResultRef()
    command_id = new_uuid4()

    result = ProposalDecisionService(
        factory,
        sr_customer_classification_participant=participant,
    ).accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_customer_reconciliation",
    )

    assert {result_type for result_type, _result_id in result.owner_result_refs} == {
        "service_request_customer_history",
        "sr_classification_event",
    }
    assert ("sr_classification_event", participant.classification_event_id) in result.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        orchestration_refs = snapshot.connection.execute(
            "SELECT r.result_type,r.result_id FROM audit_event_results r "
            "JOIN audit_events e ON e.audit_event_id=r.audit_event_id "
            "WHERE e.command_id=? AND e.action_type='ticket_import.proposal_decided' "
            "ORDER BY r.result_type,r.result_id",
            (command_id,),
        ).fetchall()
        assert ("sr_classification_event", participant.classification_event_id) in {
            (str(row[0]), str(row[1])) for row in orchestration_refs
        }

        ticket_refs = snapshot.connection.execute(
            "SELECT r.result_type,r.result_id FROM audit_event_results r "
            "JOIN audit_events e ON e.audit_event_id=r.audit_event_id "
            "WHERE e.command_id=? AND e.action_type='ticket.service_request.customer_changed'",
            (command_id,),
        ).fetchall()
        assert {str(row[0]) for row in ticket_refs} == {"service_request_customer_history"}
