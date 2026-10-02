export type RecordRef = Readonly<{record_type: string; record_id: string; revision_token: string | null}>;
export type Selection = Readonly<{active_id: string | null; selected_id: string | null; member_ids: readonly string[];
  focused_control_id: string | null; opened_ref: RecordRef | null}>;
export const emptySelection: Selection = {active_id: null, selected_id: null, member_ids: [], focused_control_id: null, opened_ref: null};
export type SurfaceState = Readonly<{selection: Selection; tab: string; pane: 'work' | 'communications';
  filters: Readonly<Record<string, string>>; scrollAnchors: Readonly<Record<string, string>>;
  dirty: boolean; errors: Readonly<Record<string, string>>; focusToken: string | null}>;

/** Stores interaction intent only. Domain DTOs and message bodies have no slot. */
export class UiStore {
  private state: SurfaceState;
  private collectionOrder:readonly string[]=Object.freeze([]);
  private readonly listeners = new Set<() => void>();
  private freeze(value: SurfaceState): SurfaceState {
    return Object.freeze({...value, filters: Object.freeze({...value.filters}), errors: Object.freeze({...value.errors}),
      scrollAnchors: Object.freeze({...value.scrollAnchors}), selection: Object.freeze({...value.selection,
        member_ids: Object.freeze([...value.selection.member_ids]), opened_ref: value.selection.opened_ref ? Object.freeze({...value.selection.opened_ref}) : null})});
  }
  constructor(initial: SurfaceState) { this.state = this.freeze(initial); }
  getSnapshot = (): SurfaceState => this.state;
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  getCollectionOrder=():readonly string[]=>this.collectionOrder;
  rememberCollectionOrder=(ids:readonly string[]):void=>{
    if(ids.length>200||ids.some(id=>typeof id!=='string'||id.length===0)||new Set(ids).size!==ids.length)throw new Error('Invalid bounded collection order');
    this.collectionOrder=Object.freeze([...ids]);
  };
  dispatch = (change: Partial<SurfaceState>): void => {
    this.state = this.freeze({...this.state, ...change});
    for (const listener of this.listeners) listener();
  };
}
