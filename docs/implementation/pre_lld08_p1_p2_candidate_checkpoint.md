# Pre-LLD-08 P1/P2 integration validation checkpoint

Date: 2026-09-23  
Candidate implementation parent: `3a0abd73cc0eab2f134216bd7eb8c2b4158f19f2`  
Reconciled design: `d3f24ca9752a2ac9cd1a5f9cb9b38dd352681338`  
Design integrity: LLD Spec Integrity #926 SUCCESS at exact design SHA.

Scope of the pending candidate verification:

- Failed startup: retain server, executor futures, active UoWs, run security, registry and data-instance OS lock until real drain; bounded failed-start cleanup recovery; pre-lock write admission closed.
- Existing/fresh regressions: request/background workers with and without UoW, independent process exclusion, partial server start, rollback, cleanup retries and normal shutdown budget accounting.
- LLD-03 point query: read-time current-affiliation mismatch warning for current customer_contact and aligned handler; immutable context, prior reviewed mismatch, null affiliation and historical stale handler behavior preserved.
- LLD-02 T013 and SR context acceptance strengthened. Design query and acceptance packet reconciled first; no new schema or normalized product rule.
- Reference case ledger corrected from stale 24/6/6/1 to actual 26 reviewed / 6 pending CI / 4 partial cross-packet / 1 deferred.

Historical: implementation CI #866 SUCCESS at ab26153f... predates these changes; CI #867 FAILURE at 4f3e305... has the known SR warning assertion. No current candidate runtime CI pass, full P3 SQL-work budget or P4 complete semantic certification exists at the time this checkpoint record is written.

The next implementation push triggers a **single coherent integration validation** of these P1/P2 slices (Windows Python 3.13 and 3.14; Ubuntu Python 3.14; release-schema manifest; packaged wheel/resources). This is an intermediate defect-regression checkpoint, not final pre-LLD-08 promotion evidence. Do not move main or start LLD-08. Final closure still requires the measured P3 SQL follow-ups, full P4 assertions/cross-packet evidence and a final exact-pair supported matrix.
