import {useLayoutEffect,useRef,useState,useSyncExternalStore,type ReactNode} from 'react';
import {isNestedControl,restoreSelection,selectionOpen,type Row} from '../interactions/selection-open';
import {UiStore, type RecordRef} from '../state/ui-store';
export function SelectableCollection({rows, store, render, open, multi = false, selectionFollowsFocus = true}: {
  rows: readonly Row[]; store: UiStore; render: (row: Row) => ReactNode; open: (ref: RecordRef) => void;
  multi?: boolean; selectionFollowsFocus?: boolean;
}) {
  if (rows.length > 200 || rows.some(row=>typeof row.id!=='string'||row.id.length===0)
    || new Set(rows.map(row => row.id)).size !== rows.length) throw new Error('Collection requires a bounded unique owner page');
  const container = useRef<HTMLDivElement>(null); const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const focusedRow=useRef<string|null>(null);
  const [explanation,setExplanation]=useState<string|null>(null);
  const rowIdentity=JSON.stringify(rows.map(row=>[row.id,row.eligible]));
  useLayoutEffect(()=>{
    const selection=store.getSnapshot().selection;const eligible=new Set(rows.filter(row=>row.eligible).map(row=>row.id));
    const missing=(selection.active_id!==null&&!eligible.has(selection.active_id))
      ||(selection.selected_id!==null&&!eligible.has(selection.selected_id));
    if(missing||selection.member_ids.some(id=>!eligible.has(id))){
      const restored=missing?restoreSelection(selection,rows,store.getCollectionOrder()):{selection:{...selection,member_ids:selection.member_ids.filter(id=>eligible.has(id))},explanation:null};
      store.dispatch({selection:restored.selection});setExplanation(restored.explanation?.replace('focus moved','selection moved').replace('focus returned','selection returned')??null);
      if(focusedRow.current!==null&&!eligible.has(focusedRow.current)
        &&(document.activeElement===document.body||container.current?.contains(document.activeElement))){
        const target=Array.from(container.current?.querySelectorAll<HTMLElement>('[data-row-id]')??[])
          .find(node=>node.dataset.rowId===restored.selection.active_id);
        (target??container.current)?.focus();focusedRow.current=restored.selection.active_id;
      }
    }
    store.rememberCollectionOrder(rows.map(row=>row.id));
  },[rowIdentity,store]);
  const dispatch = (event: Parameters<typeof selectionOpen>[1]): void => {
    setExplanation(null);
    const before = store.getSnapshot().selection; const next = selectionOpen(before, event); store.dispatch({selection: next});
    if (event.kind === 'open' && next.opened_ref && next !== before) open(next.opened_ref);
  };
  return <><div ref={container} role="list" aria-label="Records" data-scroll-owner="y" tabIndex={-1}
    onFocusCapture={event=>{focusedRow.current=(event.target as HTMLElement).closest<HTMLElement>('[data-row-id]')?.dataset.rowId??null;}}
    onBlurCapture={event=>{if(event.relatedTarget&&!event.currentTarget.contains(event.relatedTarget as Node))focusedRow.current=null;}}>{rows.map((row, index) => <div role="listitem" key={row.id}
    data-row-id={row.id} aria-current={state.selection.selected_id === row.id ? 'true' : undefined}
    data-focus-token={'row:'+row.id}
    tabIndex={row.eligible && (state.selection.active_id === row.id || (state.selection.active_id === null && index === 0)) ? 0 : -1}
    onClick={event => dispatch({kind: 'click', row, nestedControl: isNestedControl(event.target, event.currentTarget)})}
    onDoubleClick={event => dispatch({kind: 'open', row, nestedControl: isNestedControl(event.target, event.currentTarget)})}
    onKeyDown={event => {
      if (isNestedControl(event.target, event.currentTarget)) return;
      if (event.key === 'Enter') {event.preventDefault(); dispatch({kind: 'open', row, nestedControl: false});}
      else if (event.key === ' ') {event.preventDefault(); dispatch({kind: 'space', row, multi});}
      else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); const eligible = rows.filter(value => value.eligible); const at = eligible.findIndex(value => value.id === row.id);
        const next = eligible[Math.max(0, Math.min(eligible.length - 1, at + (event.key === 'ArrowDown' ? 1 : -1)))];
        if (next) {dispatch({kind: 'arrow', row: next, selectionFollowsFocus});
          Array.from(container.current?.querySelectorAll<HTMLElement>('[data-row-id]') ?? []).find(node => node.dataset.rowId === next.id)?.focus();}
      }
    }}>{multi && <input type="checkbox" aria-label={'Include ' + row.id} checked={state.selection.member_ids.includes(row.id)} disabled={!row.eligible}
      onChange={() => dispatch({kind: 'space', row, multi: true})}/>} {render(row)}
      {row.route && <button type="button" data-focus-token={'record:'+row.id} disabled={!row.eligible} onClick={() => dispatch({kind: 'open', row, nestedControl: false})}>Open record</button>}
    </div>)}</div>{explanation&&<p role="status">{explanation}</p>}</>;
}
