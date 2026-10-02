export type ActionAvailability = Readonly<{state: 'AVAILABLE' | 'BLOCKED' | 'INDETERMINATE'; reason: string | null; remediation: string | null}>;
const confirmation = new Map([
  ['infrastructure.device_reference.promote_new', 'deliberate_hold'], ['tickets.rfc.terminal_cascade.execute', 'impact_preview_plus_hold'],
  ['tickets.rfc.hard_delete', 'impact_preview_plus_hold'],
  ['objectives.grouping.accept', 'impact_preview'], ['objectives.hard_delete', 'impact_preview'], ['inventory.bulk.accept', 'impact_preview'],
  ['inventory.destructive.confirm', 'impact_preview'], ['infrastructure.workbook.accept', 'impact_preview'], ['ui.working_copy.discard', 'ordinary'],
]);
export function confirmationTier(actionKind: string): string | null {return confirmation.get(actionKind) ?? null;}
export function ActionButton({label, actionKind, availability, invoke}: {
  label: string; actionKind: string; availability: ActionAvailability; invoke: (tier: string) => void;
}) {
  const tier = confirmationTier(actionKind); const enabled = availability.state === 'AVAILABLE' && tier !== null;
  return <div><button type="button" disabled={!enabled} onClick={() => {if (enabled && tier) invoke(tier);}}>{label}</button>
    {!enabled && <p>{availability.reason ?? 'Action availability is indeterminate.'}{availability.remediation && ' ' + availability.remediation}</p>}</div>;
}
