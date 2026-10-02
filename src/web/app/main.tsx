import {createRoot} from 'react-dom/client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {SomaShell} from '../components/SomaShell';
import {resolveRoute, RouteNavigation, type ReturnState} from './router';
import {TicketWorkbench} from './TicketWorkbench';
import {Modal} from '../components/Modal';
import {AppearanceSettings} from '../components/AppearanceSettings';
import {ObjectiveWorkspace, ObjectiveDetail} from './ObjectiveWorkspace';
import {InfrastructureWorkspace} from './InfrastructureWorkspace';
import {InventoryWorkspace} from './InventoryWorkspace';
import {ReferenceSettings} from './ReferenceSettings';
import {SlaCatalogSettings} from './SlaCatalogSettings';
import {CommunicationSettings} from './CommunicationSettings';
import {ObjectiveSettings} from './ObjectiveSettings';
import '../styles/soma.css';

function Application() {
  const [path, setPath] = useState(location.pathname);
  const [dirty, setDirty] = useState(false); const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [restored, setRestored] = useState<ReturnState | null>(null); const dirtyRef = useRef(false);
  const returnState = useRef<(() => ReturnState | null) | null>(null); const navigation = useRef<RouteNavigation | null>(null);
  const updateDirty = useCallback((value: boolean) => {dirtyRef.current = value; setDirty(value);}, []);
  const captureReturnState = useCallback((capture: () => ReturnState | null) => {returnState.current = capture;}, []);
  const application = useRef<HTMLDivElement>(null); const fallback = useCallback(() => document.getElementById('main-content'), []);
  useEffect(() => {
    const controller = new RouteNavigation(location.pathname, {replace: (state, next) => history.replaceState(state, '', next),
      push: (state, next) => history.pushState(state, '', next), go: delta => history.go(delta)}, () => dirtyRef.current,
      () => returnState.current?.() ?? null, (next, state) => {returnState.current = null; setRestored(state); setPath(next);}, setPendingPath);
    navigation.current = controller; setPath(location.pathname);
    const change = (event: PopStateEvent) => controller.pop(location.pathname, event.state);
    window.addEventListener('popstate', change); return () => {navigation.current = null; window.removeEventListener('popstate', change);};
  }, []);
  const route = resolveRoute(path);
  const navigate = (next: string): void => {
    navigation.current?.navigate(next);
  };
  return <><div ref={application}><SomaShell path={path} dirty={dirty} navigate={navigate}>
    {route?.surface === 'sr_workbench' && route.recordId ? <TicketWorkbench key={path} id={route.recordId} type="service_request" onDirtyChange={updateDirty} restored={restored} onReturnState={captureReturnState}/> :
      route?.surface === 'rfc_workbench' && route.recordId ? <TicketWorkbench key={path} id={route.recordId} type="rfc" onDirtyChange={updateDirty} restored={restored} onReturnState={captureReturnState}/> :
      route?.surface === 'objectives' ? <ObjectiveWorkspace navigate={navigate} restored={restored} onReturnState={captureReturnState}/> :
      route?.surface === 'infrastructure' ? <InfrastructureWorkspace restored={restored} onReturnState={captureReturnState}/> :
      route?.surface === 'inventory' ? <InventoryWorkspace restored={restored} onReturnState={captureReturnState}/> :
      route?.surface === 'objective_detail' && route.recordId ? <ObjectiveDetail key={path} id={route.recordId}/> :
      route?.surface === 'appearance_settings' ? <AppearanceSettings/> :
      route?.surface === 'communication_settings' ? <CommunicationSettings/> :
      route?.surface === 'settings' ? <><h2>Presentation preferences</h2><a href="/settings/appearance" onClick={event => {if (!event.ctrlKey && !event.metaKey && !event.shiftKey) {event.preventDefault(); navigate('/settings/appearance');}}}>Appearance preferences</a>
        <p><a href="/settings/communications" onClick={event=>{if(!event.ctrlKey&&!event.metaKey&&!event.shiftKey){event.preventDefault();navigate('/settings/communications');}}}>Communication processing and housekeeping</a></p>
        <ObjectiveSettings/><ReferenceSettings/><SlaCatalogSettings/></> :
      <p role="status">{route ? 'This workspace binding is under implementation.' : 'Page not found.'}</p>}
  </SomaShell></div>{pendingPath && <Modal title="Leave unsaved changes?" application={application} fallback={fallback} close={() => navigation.current?.cancel()}>
    <p>This edit flow has unsaved UI values. A recovery checkpoint does not save accepted operational state.</p>
    <button type="button" onClick={() => {updateDirty(false); navigation.current?.confirm();}}>Leave this edit flow</button>
  </Modal>}</>;
}
const root = document.getElementById('root');
if (!root) throw new Error('SOMA root is missing');
createRoot(root).render(<Application/>);
