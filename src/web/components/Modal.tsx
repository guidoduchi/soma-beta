import {useEffect, useId, useRef, type ReactNode, type RefObject} from 'react';
const focusable = 'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]';
export function Modal({title, children, application, fallback, close, dismissible = true, error = null}: {
  title: string; children: ReactNode; application: RefObject<HTMLElement | null>; fallback: () => HTMLElement | null;
  close: () => void; dismissible?: boolean; error?: string | null;
}) {
  const id = useId(); const dialog = useRef<HTMLDivElement>(null); const invoker = useRef(document.activeElement);
  useEffect(() => {
    const app = application.current; const node = dialog.current;
    if (!app || !node) return;
    if (app.inert) throw new Error('Nested modal is not allowed');
    const overflow = document.documentElement.style.overflow;
    app.inert = true; document.documentElement.style.overflow = 'hidden';
    const safe = node.querySelector<HTMLElement>('[data-safe-focus]:not(:disabled)');
    (safe ?? node).focus();
    return () => {
      app.inert = false; document.documentElement.style.overflow = overflow;
      const previous = invoker.current;
      if (previous instanceof HTMLElement && previous.isConnected && !previous.matches(':disabled,[inert]') && previous.getClientRects().length) previous.focus();
      else fallback()?.focus();
    };
  }, [application, fallback]);
  useEffect(() => {if (error) dialog.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();}, [error]);
  return <div className="modal-backdrop"><div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}
    className="modal" data-scroll-owner="y" onKeyDown={event => {
      if (event.key === 'Escape' && dismissible) {event.stopPropagation(); close();}
      if (event.key !== 'Tab') return;
      const nodes = Array.from(dialog.current?.querySelectorAll<HTMLElement>(focusable) ?? []).filter(node => node.getClientRects().length > 0 && !node.closest('[hidden]'));
      const first = nodes[0]; const last = nodes.at(-1);
      if (!first) {event.preventDefault(); dialog.current?.focus();}
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {event.preventDefault(); last?.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
    }}>
      <h2 id={id}>{title}</h2>{error && <p role="alert">{error}</p>}{children}
      <button type="button" data-safe-focus disabled={!dismissible} onClick={close}>Cancel</button>
    </div></div>;
}
