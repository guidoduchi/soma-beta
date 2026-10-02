import {useEffect, useState, type ReactNode} from 'react';
import {ownerQuery, OwnerRequestError} from '../data/http';
/** A scoped query retains the accepted render only for the same identity. */
export function OwnerProjection<T>({path, render,refreshKey=0}: {path: string; render: (value: T) => ReactNode;refreshKey?:number}) {
  const [accepted, setAccepted] = useState<{path: string; value: T} | null>(null);
  const [state, setState] = useState<'loading' | 'accepted' | 'error'>('loading'); const [retry, setRetry] = useState(0); const [auth, setAuth] = useState(false);
  useEffect(() => {
    const abort = new AbortController(); setState('loading'); setAuth(false);
    void ownerQuery<T>(path, abort.signal).then(value => {if (!abort.signal.aborted) {setAccepted({path, value}); setState('accepted');}})
      .catch(error => {if (!abort.signal.aborted) {setState('error'); setAuth(error instanceof OwnerRequestError && error.status === 401);}});
    return () => abort.abort();
  }, [path, retry,refreshKey]);
  let content: ReactNode = null;
  if (accepted?.path === path) {
    try {content = render(accepted.value);} catch {content = <p role="alert">The owner projection could not be rendered. Refresh accepted state.</p>;}
  }
  return <>{state === 'loading' && <p role="status">Loading accepted state.</p>}
    {state === 'error' && <><p role="alert">{auth ? 'Authentication is required to view accepted state.' : 'The owning query is unavailable. Retained values may be stale.'}</p>
      <button type="button" onClick={() => setRetry(retry + 1)}>Retry accepted state</button></>}
    {content}</>;
}
