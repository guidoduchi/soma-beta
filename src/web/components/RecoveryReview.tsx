import {useState, type ReactNode} from 'react';
export type RecoveryFreshness = 'CURRENT' | 'STALE' | 'TARGET_MISSING' | 'INDETERMINATE';
export function RecoveryReview({freshness, accepted, workingCopy, dirtyPaths, restore, discard, reapplyReviewed}: {
  freshness: RecoveryFreshness; accepted: ReactNode; workingCopy: ReactNode; dirtyPaths: readonly string[];
  restore: () => void; discard: () => Promise<void>;
  reapplyReviewed?: () => void;
}) {
  const [reviewed, setReviewed] = useState(false); const [pending, setPending] = useState(false); const [error, setError] = useState<string | null>(null);
  const blocked = freshness === 'TARGET_MISSING' || freshness === 'INDETERMINATE';
  return <section aria-label="Working copy recovery">
    <p>Recovering this copy restores unsaved UI values. It does not save accepted operational state.</p>
    <p role={freshness === 'CURRENT' ? 'status' : 'alert'}>{freshness === 'CURRENT' ? 'The accepted revision matches this copy.' :
      freshness === 'STALE' ? 'Accepted state changed. Review both versions before restoring.' :
      freshness === 'TARGET_MISSING' ? 'The target is unavailable. This copy is preserved; save is blocked.' : 'Target freshness is indeterminate. This copy is preserved; save is blocked.'}</p>
    <h2>Accepted current values</h2>{accepted}<h2>Unsaved working-copy values</h2>{workingCopy}
    <p>Changed fields: {dirtyPaths.join(', ') || 'none'}</p>
    {freshness === 'STALE' && <label><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)}/>I reviewed the current values and my unsaved changes.</label>}
    <button type="button" disabled={blocked || pending || (freshness === 'STALE' && (!reviewed || !reapplyReviewed))}
      onClick={() => {if (freshness === 'STALE') reapplyReviewed?.(); else restore();}}>
      {freshness === 'STALE' ? 'Reapply reviewed changes' : 'Restore as unsaved changes'}</button>
    <button type="button" disabled={pending} onClick={() => {setPending(true); setError(null); void discard().catch(() => setError('Discard failed. The copy remains available; refresh its generation and retry.')).finally(() => setPending(false));}}>Discard recovery copy</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
