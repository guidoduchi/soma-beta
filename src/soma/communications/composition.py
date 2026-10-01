"""Static packet assembly; host security and native release packaging remain owned by LLD-12."""
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry

from soma.communications.api.routes_communications import CommunicationRouteAdapter
from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS, JOB_TYPES
from soma.communications.jobs.processing import CommunicationProcessingWorker
from soma.communications.jobs.housekeeping import CommunicationHousekeepingWorker
from soma.communications.jobs.identity_reconciliation import CommunicationIdentityReconciliationWorker
from soma.communications.services.identity_providers import CommunicationIdentityProviders
from soma.communications.services.processing import CommunicationProcessingService, CommunicationReconstructionRequestParticipant
from soma.communications.services.source_config import SourceConfigurationService
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.proposals import CommunicationProposalService
from soma.communications.services.proposal_evidence import CommunicationProposalEvidenceProvider
from soma.communications.services.proposal_disposition import CommunicationProposalDispositionParticipant
from soma.communications.services.identity_reconciliation import CommunicationIdentityReconciliationService
from soma.communications.services.terminal import ServiceRequestTerminalCommunicationParticipant, RfcTerminalCommunicationParticipant
from soma.communications.services.dependencies import InventoryCommunicationDependencyProvider
from soma.communications.services.drafts import MsgDraftService
from soma.communications.queries.previews import CommunicationPreviews
from soma.communications.queries.communications import CommunicationQueries
from soma.communications.queries.sources import SourceQueries
from soma.communications.queries.coverage import CoverageQueries
from soma.communications.queries.proposals import ProposalQueries
from soma.communications.queries.jobs import JobQueries
from soma.communications.queries.housekeeping import HousekeepingQueries
from soma.communications.queries.summaries import SummaryQueries, CommunicationSummaryProvider, CommunicationPanelProjectionProvider
from soma.communications.services.job_control import CommunicationJobControlService


@dataclass(frozen=True)
class CommunicationsRuntime:
    coordinator: object
    commands: object
    queries: object
    providers: object
    workers: object
    connection_factory: object

    def routes(self, *, actor_kind, actor_id=None):
        if not isinstance(actor_kind, str) or not actor_kind:
            raise ValidationError("Communications routes require authenticated actor context")
        handlers = dict(self.queries)
        handlers.update({name: partial(handler, actor_kind=actor_kind, actor_id=actor_id) for name, handler in self.commands.items()})
        from soma.communications.api.routes_communications import COMMUNICATION_ROUTE_SPECS
        return CommunicationRouteAdapter({row["handler"]: handlers[row["handler"]] for row in COMMUNICATION_ROUTE_SPECS})

    def dispatch(self, claim):
        worker = self.workers.get(claim.job_type)
        if worker is None:
            raise IntegrityFailure("Communication job has no installed worker")
        return worker.run(claim)

    def schedule(self):
        from soma.communications.jobs.scheduling import CommunicationSchedule
        return CommunicationSchedule(self)

    def claim_next(self, run_id, now):
        def eligible(writer, job_id, job_type, version):
            if job_type not in self.workers:
                return False
            from soma.communications.repositories.sources import one
            scope = one(writer, "SELECT source_scope_id FROM communication_job_scopes WHERE job_id=?", (job_id,))
            if scope is None:
                raise IntegrityFailure("Communication claim has no owning scope")
            if scope["source_scope_id"] is None:
                return True
            # Foundation host has at most two executors. Start with its indexed
            # running set, then exact PK owner lookups, never historical scopes.
            return writer.connection.execute("SELECT 1 FROM durable_jobs d INDEXED BY idx_jobs_state_due "
                "JOIN communication_job_scopes s ON s.job_id=d.job_id WHERE d.state='running' AND s.source_scope_id=? LIMIT 1",
                (scope["source_scope_id"],)).fetchone() is None
        return self.coordinator.claim_next(run_id, now, eligible=eligible)


def build_communications_runtime(connection_factory, adapter, *, proof_provider=None, clock=utc_epoch_seconds,
                                 identity_providers=None, msg_writer=None, msg_publisher=None):
    from soma.tickets.communication_identity import TicketCommunicationIdentityProvider
    from soma.objectives_tasks.services.communication_identity import TaskObjectiveCommunicationIdentityProvider
    from soma.inventory.services.participants import InventoryCommunicationIdentityProvider, InventoryProposalTargetService
    identities = identity_providers or CommunicationIdentityProviders(TicketCommunicationIdentityProvider(),
        TaskObjectiveCommunicationIdentityProvider(), InventoryCommunicationIdentityProvider())
    coordinator = DurableJobCoordinator(connection_factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS), clock=clock)
    settings = CommunicationSettingsService(connection_factory)
    processing = CommunicationProcessingService(connection_factory, identities, coordinator, adapter=adapter, proof_provider=proof_provider, clock=clock)
    housekeeping = HousekeepingService(connection_factory)
    evidence = CommunicationProposalEvidenceProvider(identities, InventoryProposalTargetService())
    disposition = CommunicationProposalDispositionParticipant(connection_factory, clock=clock)
    proposals = CommunicationProposalService(connection_factory, identity_providers=identities, evidence_provider=evidence, clock=clock)
    drafts = MsgDraftService(connection_factory, identities, writer=msg_writer, publisher=msg_publisher)
    previews = CommunicationPreviews(connection_factory, adapter, identities)
    messages = CommunicationQueries(connection_factory)
    summaries = CommunicationSummaryProvider(identities)
    reconciliation = CommunicationIdentityReconciliationService(connection_factory, identities, coordinator, clock=clock)
    reconstruction = CommunicationReconstructionRequestParticipant(connection_factory, identities, coordinator)
    commands = {
        "ConfigureSourceScope": SourceConfigurationService(connection_factory, adapter).configure_source_scope,
        "StartCommunicationProcessing": processing.start_processing,
        "StartTargetedBackfill": processing.start_targeted_backfill,
        "StartDeepScan": processing.start_deep_scan,
        "DecideCommunicationLink": proposals.decide_link,
        "DecideCommunicationDomainProposal": proposals.decide_domain_proposal,
        "CorrectCommunicationLink": proposals.correct_link,
        "GenerateMsgDraft": drafts.generate_msg_draft,
        "SetCommunicationProcessingSchedule": settings.set_processing_schedule,
        "SetCommunicationOrphanGrace": settings.set_orphan_grace,
        "CancelCommunicationJob": CommunicationJobControlService(connection_factory, coordinator).cancel_job,
    }
    queries = {
        "ListCommunicationSourceScopes": SourceQueries(connection_factory).list_source_scopes,
        "PreviewSourceScopeConfiguration": previews.preview_source_scope_configuration,
        "PreviewTargetedBackfill": previews.preview_targeted_backfill,
        "PreviewDeepScan": previews.preview_deep_scan,
        "ListCommunications": messages.list_communications,
        "GetCommunication": messages.get_communication,
        "ListCommunicationLinks": messages.list_communication_links,
        "ListCommunicationProposals": ProposalQueries(connection_factory).list_proposals,
        "GetCommunicationCoverage": CoverageQueries(connection_factory).get_coverage,
        "ListCommunicationJobs": JobQueries(connection_factory).list_jobs,
        "GetCommunicationEntitySummary": SummaryQueries(connection_factory, identities).get_entity_summary,
        "ListCommunicationHousekeeping": HousekeepingQueries(connection_factory).list_housekeeping,
    }
    processing_worker = CommunicationProcessingWorker(connection_factory, identities, coordinator, adapter, clock=clock)
    workers = {JOB_TYPES[kind]: processing_worker for kind in ("ORDINARY", "TARGETED_BACKFILL", "DEEP_SCAN")}
    workers[JOB_TYPES["ORPHAN_HOUSEKEEPING"]] = CommunicationHousekeepingWorker(connection_factory, housekeeping, coordinator, clock=clock)
    workers[JOB_TYPES["IDENTITY_RECONCILIATION"]] = CommunicationIdentityReconciliationWorker(reconciliation, coordinator, clock=clock)
    providers = {"identities": identities, "settings": settings, "processing": processing, "proposal_evidence": evidence, "proposal_disposition": disposition,
        "inventory_dependencies": InventoryCommunicationDependencyProvider(), "summary": summaries,
        "panel": CommunicationPanelProjectionProvider(summaries), "housekeeping": housekeeping, "identity_reconciliation": reconciliation,
        "sr_terminal": ServiceRequestTerminalCommunicationParticipant(connection_factory, identities, reconstruction_request_participant=reconstruction),
        "rfc_terminal": RfcTerminalCommunicationParticipant(connection_factory, identities)}
    return CommunicationsRuntime(coordinator, MappingProxyType(commands), MappingProxyType(queries), MappingProxyType(providers), MappingProxyType(workers), connection_factory)
