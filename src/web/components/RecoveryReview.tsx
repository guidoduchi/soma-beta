import {useEffect, useRef, useState, type ReactNode} from 'react';
export type RecoveryFreshness = 'CURRENT' | 'STALE' | 'TARGET_MISSING' | 'INDETERMINATE';
export type RecoveryReviewIdentity = Readonly<{workingCopyId: string; generation: number; currentRevisionToken: string | null}>;
export function RecoveryReview({identity, freshness, accepted, workingCopy, dirtyPaths, restore, discard, reapplyReviewed}: {
  identity: RecoveryReviewIdentity;
  freshness: RecoveryFreshness; accepted: ReactNode; workingCopy: ReactNode; dirtyPaths: readonly string[];
  restore: () => void; discard: () => Promise<void>;
  reapplyReviewed?: () => void;
}) {
  // Review applies only to the exact recovery generation and current owner token shown.
  const reviewKey = JSON.stringify([identity.workingCopyId, identity.generation, identity.currentRevisionToken, freshness, dirtyPaths]);
  const [reviewedKey, setReviewedKey] = useState<string | null>(null); const [pending, setPending] = useState(false);
  const [error, setError] = useState<{key: string; message: string} | null>(null);
  const current = useRef(reviewKey); current.current = reviewKey; const alive = useRef(true);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  const reviewed = reviewedKey === reviewKey;
  const blocked = freshness === 'TARGET_MISSING' || freshness === 'INDETERMINATE';
  return <section aria-label="Working copy recovery">
    <p>Recovering this copy restores unsaved UI values. It does not save accepted operational state.</p>
    <p role={freshness === 'CURRENT' ? 'status' : 'alert'}>{freshness === 'CURRENT' ? 'The accepted revision matches this copy.' :
      freshness === 'STALE' ? 'Accepted state changed. Review both versions before restoring.' :
      freshness === 'TARGET_MISSING' ? 'The target is unavailable. This copy is preserved; save is blocked.' : 'Target freshness is indeterminate. This copy is preserved; save is blocked.'}</p>
    <h2>Accepted current values</h2>{accepted}<h2>Unsaved working-copy values</h2>{workingCopy}
    <p>Changed fields: {dirtyPaths.join(', ') || 'none'}</p>
    {freshness === 'STALE' && <label><input type="checkbox" checked={reviewed} disabled={pending} onChange={event => setReviewedKey(event.target.checked ? reviewKey : null)}/>I reviewed the current values and my unsaved changes.</label>}
    <button type="button" disabled={blocked || pending || (freshness === 'STALE' && (!reviewed || !reapplyReviewed))}
      onClick={() => {if (freshness === 'STALE') reapplyReviewed?.(); else restore();}}>
      {freshness === 'STALE' ? 'Reapply reviewed changes' : 'Restore as unsaved changes'}</button>
    <button type="button" disabled={pending} onClick={() => {setPending(true); setError(null); const captured = reviewKey;
      void Promise.resolve().then(discard).catch(() => {if (alive.current && current.current === captured) setError({key: captured,
        message: 'Discard failed. The copy remains available; refresh its generation and retry.'});}).finally(() => {if (alive.current) setPending(false);});}}>Discard recovery copy</button>
    {error?.key === reviewKey && <p role="alert">{error.message}</p>}
  </section>;
}
