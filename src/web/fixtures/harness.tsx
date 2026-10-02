import {createRoot} from 'react-dom/client';
import {useCallback, useRef, useState} from 'react';
import {SomaShell} from '../components/SomaShell';
import {WorkbenchShell, srTabs} from '../components/WorkbenchShell';
import {Modal} from '../components/Modal';
import {Autocomplete, type OptionQuery} from '../interactions/autocomplete';
import {UiStore, emptySelection} from '../state/ui-store';
import {BoundedCollection} from '../components/BoundedCollection';
import {ActionButton} from '../components/ActionButton';
import {HoldButton} from '../interactions/HoldButton';
import '../styles/soma.css';

// Development/test-only synthetic data. Never imported by the production entry.
const store = new UiStore({selection: emptySelection, tab: 'Overview', pane: 'work', filters: {}, scrollAnchors: {}, dirty: false, errors: {}, focusToken: null});
const query: OptionQuery = async (input, _filters, cursor, _limit, signal) => {
  await new Promise<void>(resolve => setTimeout(resolve, input === 'slow' ? 100 : 10));
  if (signal.aborted) throw new Error('Aborted fixture request');
  const offset = cursor === null ? 0 : 25;
  return {items: Array.from({length: 25}, (_, index) => ({id: String(index + offset), label: `${input || 'Option'} ${index + offset}`, eligible: index !== 2, reason: index === 2 ? 'Synthetic owner blocker' : null})), nextCursor: 'additional'};
};
const holdBinding = {actionKind: 'tickets.rfc.hard_delete', targetType: 'RFC', targetId: 'synthetic-RFC', revision: 1, previewFingerprint: 'a'.repeat(64), route: '/tickets/rfc/synthetic-RFC'};
function Notes() {
  const [note, setNote] = useState('');
  return <label>Unsaved note<textarea aria-label="Unsaved note" value={note} onChange={event => {setNote(event.target.value); store.dispatch({dirty: true});}}/></label>;
}
function Fixture() {
  const application = useRef<HTMLDivElement>(null); const invoker = useRef<HTMLButtonElement>(null);
  const [modal, setModal] = useState(false); const [accepted, setAccepted] = useState('none'); const [count, setCount] = useState(0);
  const [showInvoker, setShowInvoker] = useState(true); const [modalValue, setModalValue] = useState(''); const [validationError, setValidationError] = useState<string | null>(null);
  const fallback = useCallback(() => document.getElementById('main-content'), []);
  return <><div ref={application}><SomaShell path="/tickets/sr/synthetic-SR" navigate={() => {}} warnings={['Synthetic coverage is partial']}>
    <WorkbenchShell store={store} tabs={srTabs} domainDraft renderTab={tab => tab === 'Notes' ? <Notes/> : tab !== 'Overview' ? <h2>{tab}</h2> : <>
      <h2>{tab}</h2>{showInvoker && <button ref={invoker} type="button" onClick={() => setModal(true)}>Review synthetic action</button>}
      <ActionButton label="Blocked owner action" actionKind="inventory.bulk.accept" availability={{state: 'BLOCKED', reason: 'Synthetic dependency exists.', remediation: 'Review dependencies.'}} invoke={() => setCount(count + 1)}/>
      <ActionButton label="Unknown owner action" actionKind="synthetic.unknown" availability={{state: 'INDETERMINATE', reason: null, remediation: null}} invoke={() => setCount(count + 1)}/>
      <Autocomplete id="fixture-options" label="Synthetic reference" filterFingerprint={'a'.repeat(64)} query={query} onAccept={option => setAccepted(option.id)}/>
      <p>Accepted option: <output>{accepted}</output></p><p>Commands: <output>{count}</output></p>
      <HoldButton label="Hold synthetic delete" binding={holdBinding} available providers={{
        issue: async () => ({challengeId: 'synthetic-challenge', clientNonce: 'synthetic-nonce', expiresMonotonicMs: performance.now() + 10000}),
        complete: async () => 'synthetic-proof', submit: async () => {setCount(value => value + 1); return 'accepted';}}}/>
      <BoundedCollection caption="Synthetic bounded comparison" rows={Array.from({length: 200}, (_, index) => ({id: String(index), cells: [String(index), 'Wide synthetic comparison '.repeat(8)]}))} next onNext={() => {}}/>
      <p>{'<script>window.FORBIDDEN_MARKER=true</script>'}</p>
    </>} communications={<><h2>Communications</h2><p role="alert">Canonical communication provider unavailable.</p><p>Coverage remains partial. Operational work is available.</p></>}/>
  </SomaShell></div>{modal && <Modal title="Synthetic impact review" application={application} fallback={fallback} close={() => setModal(false)} error={validationError}>
    <p>Review the synthetic consequences.</p><button type="button" onClick={() => {setCount(count + 1); setModal(false);}}>Accept synthetic action</button>
    <label>Review reason<input aria-label="Review reason" aria-invalid={validationError !== null} value={modalValue} onChange={event => setModalValue(event.target.value)}/></label>
    <button type="button" onClick={() => setValidationError('Synthetic owner validation failed. Review the reason.')}>Inject validation failure</button>
    <button type="button" onClick={() => setShowInvoker(false)}>Remove synthetic invoker</button>
  </Modal>}</>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
