import type {RecordRef, Selection} from '../state/ui-store.js';
export type Row = Readonly<{id: string; eligible: boolean; route: RecordRef | null}>;
export type SelectionEvent =
  | {kind: 'click'; row: Row; nestedControl: boolean}
  | {kind: 'open'; row: Row; nestedControl: boolean}
  | {kind: 'arrow'; row: Row; selectionFollowsFocus: boolean}
  | {kind: 'space'; row: Row; multi: boolean};

export function selectionOpen(state: Selection, event: SelectionEvent): Selection {
  const row = event.row;
  if (!row.eligible || !row.id) return state;
  switch (event.kind) {
    case 'click': return event.nestedControl ? state : {...state, active_id: row.id, selected_id: row.id};
    case 'open': return event.nestedControl || !row.route ? state : {...state, opened_ref: row.route};
    case 'arrow': return {...state, active_id: row.id, selected_id: event.selectionFollowsFocus ? row.id : state.selected_id};
    case 'space': return !event.multi ? state : {...state, member_ids: state.member_ids.includes(row.id)
      ? state.member_ids.filter(id => id !== row.id) : [...state.member_ids, row.id]};
  }
}

export function isNestedControl(target: EventTarget | null, rowElement: Element): boolean {
  return target instanceof Element && target !== rowElement && Boolean(target.closest('button,a,input,select,textarea,[role="button"],[role="checkbox"]'));
}

export function restoreSelection(state: Selection, survivingRows: readonly Row[], previousOrder: readonly string[] = []): {selection: Selection; explanation: string | null} {
  const eligible = new Set(survivingRows.filter(row => row.eligible).map(row => row.id));
  const positions = new Map(previousOrder.map((id, index) => [id, index]));
  const previousIndex = positions.get(state.active_id ?? state.selected_id ?? '') ?? -1;
  const nearest = previousIndex < 0 ? [] : survivingRows.filter(row => row.eligible && positions.has(row.id)).sort((a, b) =>
    Math.abs((positions.get(a.id) ?? 0) - previousIndex) - Math.abs((positions.get(b.id) ?? 0) - previousIndex)
    || (positions.get(a.id) ?? 0) - (positions.get(b.id) ?? 0));
  const fallback = nearest[0]?.id ?? survivingRows.find(row => row.eligible)?.id ?? null;
  const missing = (state.active_id !== null && !eligible.has(state.active_id)) || (state.selected_id !== null && !eligible.has(state.selected_id));
  return {selection: {...state, active_id: state.active_id && eligible.has(state.active_id) ? state.active_id : fallback,
    selected_id: state.selected_id && eligible.has(state.selected_id) ? state.selected_id : fallback,
    member_ids: state.member_ids.filter(id => eligible.has(id))}, explanation: missing ?
      (fallback ? 'The previous row is unavailable; focus moved to the nearest eligible row.' : 'The previous row is unavailable; focus returned to the collection.') : null};
}
