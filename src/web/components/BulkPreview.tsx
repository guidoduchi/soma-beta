export type BulkTarget = Readonly<{id: string; state: 'ELIGIBLE' | 'NO_CHANGE' | 'BLOCKED' | 'CONFLICT' | 'INDETERMINATE'; reason: string | null}>;
/** The owner partitions the selection; presentation never infers eligibility. */
export function validateBulkPartition(selected: readonly string[], targets: readonly BulkTarget[]): void {
  const wanted = new Set(selected), seen = new Set<string>();
  if (wanted.size !== selected.length || targets.length !== selected.length) throw new Error('Bulk preview does not cover the complete selection');
  for (const target of targets) {
    if (!wanted.has(target.id) || seen.has(target.id) || !['ELIGIBLE','NO_CHANGE','BLOCKED','CONFLICT','INDETERMINATE'].includes(target.state)) {
      throw new Error('Bulk preview partition is invalid');
    }
    seen.add(target.id);
  }
}
export function BulkPreview({selected, targets}: {selected: readonly string[]; targets: readonly BulkTarget[]}) {
  validateBulkPartition(selected, targets);
  return <section aria-label="Complete selected-target impact"><p>{selected.length} selected targets reviewed.</p>
    {(['ELIGIBLE','NO_CHANGE','BLOCKED','CONFLICT','INDETERMINATE'] as const).map(state => <p key={state}>
      {state.replaceAll('_',' ')}: {targets.filter(target => target.state === state).length}</p>)}
    <p>Only the owning command can apply its eligible partition. Other targets retain their owner-projected outcome.</p>
  </section>;
}
