import {useRef, useEffect, type ReactNode} from 'react';
import {classifyContainer, unsupportedCapabilities, useContainerWidth} from '../layout/responsive';
import {installScrollOwnership} from '../interactions/scroll-owner';
import {resolveRoute} from '../app/router';
export const workspaces = [['Overview','/overview'], ['Tickets','/tickets'], ['Objectives','/objectives'], ['Inventory','/inventory'], ['Infrastructure','/infrastructure'], ['Settings','/settings']] as const;
export function SomaShell({path, navigate, children, warnings = [], dirty = false}: {
  path: string; navigate: (path: string) => void; children: ReactNode; warnings?: readonly string[]; dirty?: boolean;
}) {
  const shell = useRef<HTMLDivElement>(null); const main = useRef<HTMLElement>(null); const width = useContainerWidth(shell);
  const route = resolveRoute(path); const missing = unsupportedCapabilities();
  useEffect(() => {
    const node = shell.current;
    if (!node) return;
    return installScrollOwnership(node, () => main.current, () => {window.dispatchEvent(new Event('soma-scroll-gesture'));});
  }, []);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent): void => {if (dirty) {event.preventDefault(); event.returnValue = '';}};
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const workspace = workspaces.find(([, base]) => route?.path === base || route?.path.startsWith(base + '/'))?.[0] ?? 'Page not found';
  return <div ref={shell} className="soma-shell" data-responsive={classifyContainer(width)}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header><span className="brand">SOMA</span><span>Local operations</span></header>
    <nav aria-label="Workspaces">{workspaces.map(([label, destination]) => <a key={destination} href={destination}
      aria-current={workspace === label ? 'page' : undefined} onClick={event => {if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey) {event.preventDefault(); navigate(destination);}}}>{label}</a>)}</nav>
    <main ref={main} id="main-content" tabIndex={-1} data-scroll-owner="y"><h1>{workspace}</h1>
      {warnings.map(warning => <p className="warning" role="status" key={warning}>Warning: {warning}</p>)}
      {missing.length ? <p role="alert">UI_BROWSER_CAPABILITY_UNSUPPORTED: {missing.join(', ')}. Required interactions are unavailable.</p> : route ? children : <p>The requested page is unavailable. Select a workspace.</p>}
    </main>
  </div>;
}
