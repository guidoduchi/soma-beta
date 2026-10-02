import {useEffect, useId, useRef, useSyncExternalStore, type ReactNode} from 'react';
import {useContainerWidth} from '../layout/responsive';
import {UiStore} from '../state/ui-store';
export const srTabs = ['Overview', 'Devices', 'Spare Parts', 'RFCs', 'Tasks', 'Notes'] as const;
export const rfcTabs = ['Overview', 'Service Requests and Devices', 'Related RFCs', 'Tasks', 'Notes'] as const;
export function WorkbenchShell({store, tabs, renderTab, communications, domainDraft = false, onDirtyChange}: {
  store: UiStore; tabs: readonly string[]; renderTab: (tab: string) => ReactNode; communications: ReactNode; domainDraft?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const container = useRef<HTMLDivElement>(null); const width = useContainerWidth(container); const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const prefix = useId();
  const tab = tabs.includes(state.tab) ? state.tab : tabs[0] ?? 'Overview'; const split = width >= 1040;
  useEffect(() => {onDirtyChange?.(state.dirty); return () => onDirtyChange?.(false);}, [state.dirty, onDirtyChange]);
  return <div ref={container} className="workbench" data-layout={split ? 'split' : 'switcher'}>
    <div className="working-status">{domainDraft && <span>Domain Draft — accepted state</span>}{state.dirty && <span>Unsaved UI changes</span>}</div>
    {!split && <div role="group" aria-label="Workbench pane"><button type="button" data-focus-token="pane:work" aria-pressed={state.pane === 'work'} onClick={() => store.dispatch({pane: 'work'})}>Work</button>
      <button type="button" data-focus-token="pane:communications" aria-pressed={state.pane === 'communications'} onClick={() => store.dispatch({pane: 'communications'})}>Communications</button></div>}
    <div className="workbench-panes">
      <section aria-label="Operational work" hidden={!split && state.pane !== 'work'} className="work-pane" data-scroll-owner="y">
        <div role="tablist" aria-label="Record sections">{tabs.map(name => <button key={name} type="button" role="tab" aria-selected={name === tab}
          data-focus-token={'tab:' + name} tabIndex={name === tab ? 0 : -1} id={prefix + '-tab-' + name.replaceAll(' ', '-')} aria-controls={prefix + '-panel-' + name.replaceAll(' ', '-')}
          onClick={() => store.dispatch({tab: name})} onKeyDown={event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault(); const index = tabs.indexOf(tab);
            const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs.at(-1) : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
            if (next) {store.dispatch({tab: next}); document.getElementById(prefix + '-tab-' + next.replaceAll(' ', '-'))?.focus();}
          }}>{name}</button>)}</div>
        {tabs.map(name => <div key={name} role="tabpanel" id={prefix + '-panel-' + name.replaceAll(' ', '-')} aria-labelledby={prefix + '-tab-' + name.replaceAll(' ', '-')}
          hidden={name !== tab}>{renderTab(name)}</div>)}
      </section>
      <aside aria-label="Communications" hidden={!split && state.pane !== 'communications'} className="communication-pane" data-scroll-owner="y">{communications}</aside>
    </div>
  </div>;
}
