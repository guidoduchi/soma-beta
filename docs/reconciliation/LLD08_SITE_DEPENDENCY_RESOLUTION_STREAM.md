# LLD-08 Site dependency resolution stream reconciliation

Status: design reconciliation for the LLD-03/LLD-05 Site dependency validators required by LLD-08.

The earlier point lookup `DeviceReferenceResolutionReader.resolution_for` is correct for
individual Device Reference views, but it is not sufficient for bounded Site archive
validation: using it alone would require Ticket and Task owners to scan every current
Device Reference relationship globally.

LLD-08 therefore extends the same read-only provider with
`list_for_site(snapshot_or_uow,site_id,cursor,limit) -> page`.

The stream:

- exposes only current Device Reference resolutions for one Site;
- is ordered by `(network_element_id, device_reference_id)`;
- has a hard page maximum of 200;
- uses the last returned pair as an exclusive keyset cursor;
- accepts the caller stable Snapshot or current UnitOfWork;
- never mutates, commits, or exposes LLD-08 private table access.

`resolution_for` remains available for one-reference views and returns the current
Network Element identity plus Site identity when resolved.

`TicketSiteDependencyValidator` treats each current active
`sr_device_reference_links` / `rfc_device_reference_links` row whose Device Reference
is currently resolved into the target Site as an operational blocker.
`TaskSiteDependencyValidator` applies the same rule to current active
`task_device_links` rows. Terminal/history state does not silently deactivate a still
current relationship; explicit unlinking is the authority that removes the blocker.

Both owner validators batch their own indexed link reads against the LLD-08 Site stream.
They do not read `device_reference_resolution_current`, `network_elements`, or
`sites` directly. Provider absence, malformed page data, or resolution uncertainty
fails closed for authoritative Site archive validation.

This reconciliation changes no Ticket, Task, Site, or Device Reference lifecycle
semantics and allocates no new persistence authority.
