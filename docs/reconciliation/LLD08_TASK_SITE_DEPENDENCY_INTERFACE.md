# LLD-05 / LLD-08 Task Site Dependency Interface Reconciliation

Status: design reconciliation for the pre-implementation LLD-08 Site dependency gap.

The LLD-08 canonical interface registry requires `TaskSiteDependencyValidator`
from LLD-05, but Tasks carry Device References rather than Infrastructure
`site_id` authority. The existing LLD-05 cross-packet registry did not declare
the reader needed to map one current Task Device Reference to its current
Infrastructure resolution.

This reconciliation adds exactly one consumed read-only interface to LLD-05:

- provider: LLD-08
- interface: `DeviceReferenceResolutionReader`
- method: `resolution_for(snapshot_or_uow, device_reference_id)`
- mutation authority: none

The provider is used only by `TaskSiteDependencyValidator`. LLD-05 continues
to own Task and `task_device_links` authority; LLD-08 continues to own
DeviceReference-to-NetworkElement resolution and Site/Network Element authority.
LLD-05 must not query LLD-08 private tables directly. The validator uses the
caller reader, and an unavailable, malformed, or otherwise indeterminate
resolution path fails closed during authoritative Site archive validation.

This change does not modify Task lifecycle semantics, Site lifecycle semantics,
migration allocation, or any previously accepted LLD-01 through LLD-07
persistence history.
