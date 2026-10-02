import {useEffect, useState} from 'react';
import {SafeUndo, type InversePreview} from '../interactions/safe-undo';
export function UndoOpportunity({undo, id, acceptedRevision}: {undo: SafeUndo; id: string; acceptedRevision: string}) {
  const [preview, setPreview] = useState<InversePreview>({state: 'INDETERMINATE', fingerprint: null, reason: 'Checking owner inverse availability.'});
  const [pending, setPending] = useState(false); const [done, setDone] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true; setPreview({state: 'INDETERMINATE', fingerprint: null, reason: 'Checking owner inverse availability.'});
    void undo.availability(id).then(value => {if (alive) setPreview(value);});
    return () => {alive = false;};
  }, [undo, id, acceptedRevision]);
  if (done) return <p role="status">The owning correction command completed.</p>;
  const available = preview.state === 'AVAILABLE' && /^[0-9a-f]{64}$/u.test(preview.fingerprint ?? '');
  return <div><button type="button" disabled={!available || pending} onClick={() => {
    setPending(true); setError(null);
    void undo.execute(id).then(success => {if (success) setDone(true); else {setPreview({state: 'INDETERMINATE', fingerprint: null, reason: 'Refresh the owning correction workflow.'}); setError('The inverse was rejected or could not be verified. Accepted state was not reversed by the UI.');}})
      .finally(() => setPending(false));
  }}>Undo this action</button>{!available && <p>{preview.reason ?? 'No current safe inverse is available. Use the owning correction workflow.'}</p>}
    {error && <p role="alert">{error}</p>}</div>;
}
