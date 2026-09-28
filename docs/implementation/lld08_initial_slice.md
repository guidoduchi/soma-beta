# LLD-08 initial domain implementation

Branch base: dd043b90 (existing implementation checkpoint).
Normative design: d3f24ca9752a2ac9cd1a5f9cb9b38dd352681338, the design revision
pinned by implementation CI. Sources: spec/lld/infrastructure/algorithms/
{rack-occupancy,containment-cycle,ip-normalization}.json, bounds.json, errors.json
and implementation/module-map.json.

This slice implements pure domain rules in domain/placement.py and
domain/relationships.py: rack height and half-open U intervals, same-Site
placement geometry, iterative current-parent cycle validation with a 1024-node
hard limit, and host-only canonical IPv4/IPv6 normalization.

Focused tests exercise the domain portions of acceptance A013-A014, A017-A020,
A030-A031, A039-A041 and corrupt ancestry from F016. These are NOT claims of
complete command-level or transactional acceptance coverage.

No schema or command authority is added in this slice. Follow-on work must:
- Allocate the next implementation migration without renumbering existing SQL.
- Implement Site creation with the shared-UoW Dispatch Location participant.
- Add repositories, audited commands, exact replay results, queries and routes.
- Revalidate placement occupancy with an indexed same-Rack query inside the
  writer UoW, excluding the element being moved.
- Re-run containment against current rows in that UoW and enforce eligibility,
  revisions and current-parent cardinality.
- Enforce same-element IP uniqueness and atomic primary selection; cross-element
  duplicate addresses remain warnings, never merge/identity authority.
- Implement remaining model/component, regularization and workbook contracts.

The user's explicit request starts LLD-08 on a separate branch. It does not close
the P3/P4 obligations recorded by the earlier pre-LLD-08 checkpoint.

## Workbook follow-on (incomplete implementation checkpoint)

This checkpoint adds `RejectInfrastructureWorkbookRun` through the
existing LLD-01 command boundary. Its terminal run transition, pending-proposal
rejection, one decision per staging row, audit, receipt and exact replay result
share one UnitOfWork. A reviewable run with prior terminal row evidence or
staging counts inconsistent with its published counts fails closed. Focused
tests cover replay, duplicate proposal rows, stale state, incomplete staging
and audit-failure rollback. A bounded repository cleanup batch may delete
terminal technical staging and cascade proposals only after the migration guard
finds matching durable row decisions; replay and audit evidence survive.

Read snapshots now provide workbook replay identity, history pagination and a
reviewable run proposal page. The run page follows the group sequence in the
normative `ui/workspace-state.json` and carries the complete four-field cursor.
The terminal post-cleanup proposal-count projection needs further authority
review: technical proposal rows may be deleted after durable row decisions, and
the V2 run response does not declare a separate row-decision summary. Do not
claim A071/A072 query closure from the current page implementation.

Remaining workbook work includes proposal detail, generation and staging jobs,
accepted selected mutations, security preflight, cleanup job orchestration, HTTP
host route assembly and end-to-end acceptance/failure evidence. The workbook work here is an
implementation slice, not complete LLD-08 certification.

Site customer correction and archive now reuse each cross-packet dependency
guard result within the writer UnitOfWork when checking a supplied preview
fingerprint and current blockers. A focused test asserts one guard read per
provider for both customer correction and archive.

Site archive blocker pagination now continues across the validators' 200-item
provider pages and returns a cursor when a 500-item physical page has more
rows. Focused tests cover both boundaries without expanding the public query
limit.

The workbook artifact profile now has fixed version/sheet/header declarations,
America/Guayaquil filename construction and a bounded write-only stream writer.
The writer validates export scope shape, exact Rack integers, local IDs and
explicit IP primary booleans, and keeps formula-like text literal. A verifier
captures the unpublished bytes once, checks resource bounds, ZIP parts,
relationships, profile, formulas and row counts, and returns SHA-256/size.
Atomic publication, evidence and recovery remain job work.

Owner clarification: `INFRA_EXPORT_SCOPE_V1.network_element_ids` is limited to
400 IDs, superseding the pinned packet's 100,000-ID field bound. The workbook
profile still requires one `ExportScopeJson` metadata cell bounded to 16,384
UTF-8 bytes. Runtime request validation enforces 400; the pinned design leaf
must be reconciled before design-integrity evidence can claim alignment.

Owner clarification: `infrastructure.import_directory` uses LLD-02's
`ordinary_nonsecret` storage class; all LLD-08 path-specific validation and
observational access rules remain. This supersedes only the pinned LLD-08
setting leaf's `non_secret_local_path` classification. A typed registry
definition and lexical Windows path validation are now present, with an
integration test for the unpersisted default and explicit LLD-02 SettingStore
write. An observational directory access probe now returns
`WORKBOOK_DIRECTORY_UNAVAILABLE` without creating the configured directory.
Command/job integration, deterministic nonrecursive discovery, and pinned
design reconciliation remain pending. No new SettingStore class is introduced.

Generated artifact verification now also compares export scope and generation
timestamp with the inputs that produced the unpublished artifact; it cannot
accept a different generation's metadata solely because the workbook profile
is otherwise valid.

The two workbook durable-job types now register Foundation JobTypeContracts
with closed payload/checkpoint shapes, command/request dedupe identity, bounded
technical filename and fingerprint fields, and stale-claim reconciliation
dispositions. Coordinator enqueue/coalescing has focused tests. This does not
yet enqueue jobs from the two commands or implement either worker's filesystem,
staging, publication, or crash-recovery state machine.

The Check-now request and stage-job payload require `setting_revision: rev`
(positive), but LLD-02 returns `revision=None` for an unpersisted computed
default. The packet needs an explicit default-setting freshness token or a rule
that Check-now first requires an operator-persisted setting. No synthetic
revision is assigned in the current implementation.

The Foundation `DataInstanceIdentityReader` callable is now available for
Infrastructure consumers. It returns the exact canonical UUIDv4 from the
verified caller snapshot/UnitOfWork; Infrastructure does not read the private
Foundation identity table itself. Export command enqueue and worker use remain
pending.

The LLD-08 transport adapter now resolves all 49 declared routes, validates
path-owned UUID/fingerprint identities, request DTOs and conflicting repeated
body identities, and dispatches only to explicit injected owner handlers.
LLD-12 still owns authentication, CSRF and raw request-byte enforcement; this
adapter is not yet assembled into a running HTTP host. An owner binding now
connects installed commands and queries with explicit caller-supplied
authenticated actor context and checks command response schema. Routes for
workbook commands/queries whose owners are not implemented fail closed rather
than pretending those operations are available.

The LLD-04 hardened XLSX container preflight now accepts an explicit resource
profile while retaining its exact existing defaults. LLD-08 supplies its own
256 MiB compressed, 20,000 ZIP-entry and 1 GiB expanded ceilings and maps
unsafe/unavailable source failures to Infrastructure errors. The immutable
captured byte stream is returned to the later semantic parser; import sheet,
header, formula and row-normalization checks and stage-job orchestration remain
pending. Ordinary XML parts are now declaration-scanned in bounded chunks,
including across chunk boundaries; relationship and content-type XML are still
materialized for graph validation and require measured large-file hardening
before certification at the 1 GiB ceiling.
