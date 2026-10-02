import {createRoot} from 'react-dom/client';
import {useCallback, useRef, useState} from 'react';
import {SomaShell} from '../components/SomaShell';
import {WorkbenchShell, srTabs} from '../components/WorkbenchShell';
import {OwnerProjection} from '../components/OwnerProjection';
import {RecoveryReview} from '../components/RecoveryReview';
import {CommunicationPanel, type PanelQuery} from '../components/CommunicationPanel';
import {BulkPreview} from '../components/BulkPreview';
import {ActionButton} from '../components/ActionButton';
import {Modal} from '../components/Modal';
import {Autocomplete, type OptionQuery} from '../interactions/autocomplete';
import {HoldButton} from '../interactions/HoldButton';
import {UiStore, emptySelection} from '../state/ui-store';
import '../styles/soma.css';

// Test-only, completely synthetic projections. No fixture is bundled into the application.
const states = ['empty','loading','warning','error','stale','destructive-preview','historical',
  'working-copy-recovery','keyboard-focus','autocomplete','dialog','deliberate-hold-progress'] as const;
const requested = new URLSearchParams(location.search).get('state');
const state = states.find(value => value === requested);
const store = new UiStore({selection: emptySelection, tab: 'Overview', pane: 'work', filters: {}, scrollAnchors: {}, dirty: false, errors: {}, focusToken: null});
const syntheticOptions: OptionQuery = async () => ({items: [{id: 'synthetic-option-1', label: 'Synthetic reference Alpha', eligible: true, reason: null},
  {id: 'synthetic-option-2', label: 'Synthetic reference Beta', eligible: false, reason: 'Synthetic owner blocker'}], nextCursor: null});
const historical: PanelQuery = async (targetType, targetId) => ({summary: {target_type: targetType, target_id: targetId,
  received_count: 1, sent_count: 0, unknown_count: 0, last_interaction: {known: false, utc_epoch_seconds: null, source_kind: 'UNKNOWN'}, last_direction: 'UNKNOWN', pending_proposals: 0,
  coverage_state: 'HISTORICAL', warnings: ['Synthetic retained metadata only.'], body_navigation_available: false},
  recent_messages: {items: [{communication_id: 'synthetic-message-1', subject: 'Synthetic historical subject', direction: 'RECEIVED',
    content_state: 'CONTENT_UNAVAILABLE', chronology: {known: false, utc_epoch_seconds: null, source_kind: 'UNKNOWN'}}], next_cursor: null},
  terminal_frozen: true, warnings: []});
function Fixture() {
  const application = useRef<HTMLDivElement>(null); const [modal, setModal] = useState(false);
  const [restored, setRestored] = useState(false); const [submitted, setSubmitted] = useState(0);
  const fallback = useCallback(() => document.getElementById('main-content'), []);
  if (!state) return <p role="alert">Unknown governed fixture state.</p>;
  const recovery = state === 'stale' || state === 'working-copy-recovery';
  const content = <>
    <h2>Synthetic {state} fixture</h2>
    {state === 'empty' && <p>No accepted records in this synthetic owner page.</p>}
    {(state === 'loading' || state === 'error') && <OwnerProjection path="/api/v1/tickets/service-requests/11111111-1111-4111-8111-111111111111" render={() => null}/>}
    {state === 'warning' && <ActionButton label="Synthetic blocked action" actionKind="inventory.bulk.accept"
      availability={{state: 'BLOCKED', reason: 'Synthetic dependency exists.', remediation: 'Review the owner dependency.'}} invoke={() => setSubmitted(value => value + 1)}/>}
    {recovery && <RecoveryReview identity={{workingCopyId:'11111111-1111-4111-8111-111111111111',generation:1,currentRevisionToken:'synthetic-current-1'}} freshness={state === 'stale' ? 'STALE' : 'CURRENT'} accepted={<p>Synthetic accepted note</p>}
      workingCopy={<p>Synthetic unsaved note</p>} dirtyPaths={['/note']} restore={() => setRestored(true)}
      reapplyReviewed={() => setRestored(true)} discard={async () => {}}/>}
    {state === 'destructive-preview' && <BulkPreview selected={['synthetic-1','synthetic-2','synthetic-3','synthetic-4','synthetic-5']}
      targets={(['ELIGIBLE','NO_CHANGE','BLOCKED','CONFLICT','INDETERMINATE'] as const).map((outcome, index) => ({id: `synthetic-${index + 1}`, state: outcome, reason: null}))}/>}
    {state === 'keyboard-focus' && <button type="button" onClick={() => {}}>Synthetic keyboard target</button>}
    {state === 'autocomplete' && <Autocomplete id="governed-reference" label="Synthetic reference" filterFingerprint={'a'.repeat(64)} query={syntheticOptions} onAccept={() => {}}/>}
    {state === 'dialog' && <button type="button" onClick={() => setModal(true)}>Open synthetic review</button>}
    {state === 'deliberate-hold-progress' && <HoldButton label="Hold synthetic destructive action" available
      binding={{actionKind: 'tickets.rfc.hard_delete', targetType: 'RFC', targetId: 'synthetic-RFC', revision: 1,
        previewFingerprint: 'a'.repeat(64), route: '/tickets/rfc/synthetic-RFC'}} providers={{
          issue: async () => ({challengeId: 'synthetic-challenge', clientNonce: 'synthetic-nonce', expiresMonotonicMs: performance.now() + 10000}),
          complete: async () => 'synthetic-proof', submit: async () => {setSubmitted(value => value + 1); return 'synthetic accepted';}}}/>}
    <p>Restored as unsaved: <output>{String(restored)}</output></p><p>Owner commands: <output>{submitted}</output></p>
  </>;
  return <><div ref={application}><SomaShell path="/tickets/sr/synthetic-SR" navigate={() => {}}
    warnings={state === 'warning' ? ['Synthetic coverage is partial.'] : []}>
    <WorkbenchShell store={store} tabs={srTabs} renderTab={tab => tab === 'Overview' ? content : <h2>{tab}</h2>}
      communications={state === 'historical' ? <CommunicationPanel targetType="SR" targetId="synthetic-SR" query={historical} openMessage={() => {}}/>
        : <p>Synthetic communication evidence pane.</p>}/>
    </SomaShell></div>{modal && <Modal title="Synthetic governed review" application={application} fallback={fallback} close={() => setModal(false)}>
      <p>Review the synthetic impact before proceeding.</p><button type="button" onClick={() => {}}>Synthetic primary action</button>
    </Modal>}</>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
