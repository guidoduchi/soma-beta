import {createRoot} from 'react-dom/client';
import {useState} from 'react';
import {RecoveryReview} from '../components/RecoveryReview';
import '../styles/soma.css';

// Test-only owner seam; no production edit-surface registration or owner mutation.
function Fixture() {
  const [generation, setGeneration] = useState(1); const [revision, setRevision] = useState(1);
  const [restored, setRestored] = useState(0); const [attempts, setAttempts] = useState(0);
  return <main><h1>Synthetic recovery review</h1>
    <button onClick={() => setRevision(value => value + 1)}>Refresh current owner revision</button>
    <button onClick={() => setGeneration(value => value + 1)}>Refresh recovery generation</button>
    <RecoveryReview identity={{workingCopyId:'11111111-1111-4111-8111-111111111111',generation,currentRevisionToken:'synthetic-current-'+revision}}
      freshness="STALE" accepted={<p>Current owner revision: {revision}</p>} workingCopy={<p>Recovery generation: {generation}</p>}
      dirtyPaths={['/note']} restore={() => setRestored(value => value + 1)} reapplyReviewed={() => setRestored(value => value + 1)}
      discard={async () => {setAttempts(value => value + 1); await new Promise(resolve => setTimeout(resolve, 100)); throw new Error('Synthetic conflict');}}/>
    <p>Unsaved restores: <output>{restored}</output></p><p>Discard attempts: <output>{attempts}</output></p>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
