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
