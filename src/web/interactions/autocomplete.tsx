import {useEffect, useRef, useState} from 'react';
import {QueryController, type QueryIdentity} from '../data/query-controller.js';
export type Option = Readonly<{id: string; label: string; eligible: boolean; reason: string | null}>;
export type OptionPage = Readonly<{items: readonly Option[]; nextCursor: unknown | null}>;
export type AutocompletePhase = 'minimum_input' | 'loading' | 'results' | 'no_match' | 'empty' | 'partial' | 'more_available' | 'stale' | 'warning' | 'error';
export type OptionQuery = (input: string, filterFingerprint: string, cursor: unknown | null, limit: 25, signal: AbortSignal) => Promise<OptionPage>;
export function boundedOptions(existing: readonly Option[], page: OptionPage): readonly Option[] {
  if (page.items.length > 25 || existing.length + page.items.length > 50) throw new Error('Autocomplete page exceeds its bound');
  const ids = new Set(existing.map(option => option.id));
  for (const option of page.items) {
    if (!option.id || ids.has(option.id) || typeof option.eligible !== 'boolean') throw new Error('Autocomplete identity is invalid');
    ids.add(option.id);
  }
  return [...existing, ...page.items];
}

export function Autocomplete({id, label, filterFingerprint, query, onAccept, minimumInput = 2}: {
  id: string; label: string; filterFingerprint: string; query: OptionQuery; onAccept: (option: Option) => void; minimumInput?: number;
}) {
  if (!Number.isInteger(minimumInput) || minimumInput < 1 || minimumInput > 4) throw new Error('Invalid autocomplete threshold');
  const controller = useRef(new QueryController());
  const [input, setInput] = useState(''); const [disclosed, setDisclosed] = useState(false); const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<AutocompletePhase>('minimum_input'); const [options, setOptions] = useState<readonly Option[]>([]);
  const [active, setActive] = useState<string | null>(null); const [cursor, setCursor] = useState<unknown | null>(null);
  const identity = useRef<QueryIdentity | null>(null);
  const normalized = input.trim().normalize('NFC');
  const load = async (append: boolean): Promise<void> => {
    const ticket = controller.current.start(id, normalized, filterFingerprint); identity.current = ticket.identity; setPhase('loading');
    try {
      const page = await query(normalized, filterFingerprint, append ? cursor : null, 25, ticket.signal);
      if (!controller.current.accept_response(ticket.identity)) return;
      const values = boundedOptions(append ? options : [], page);
      setOptions(values); setCursor(page.nextCursor); setOpen(true);
      setPhase(page.nextCursor !== null ? (values.length === 50 ? 'partial' : 'more_available') : values.length ? 'results' : normalized ? 'no_match' : 'empty');
    } catch {
      if (controller.current.accept_response(ticket.identity)) setPhase('error');
    }
  };
  useEffect(() => {
    controller.current.cancel(id); identity.current = null; setActive(null); setOptions([]); setCursor(null);
    if (!disclosed && Array.from(normalized).length < minimumInput) {setPhase('minimum_input'); return;}
    const timer = setTimeout(() => { void load(false); }, 150);
    return () => { clearTimeout(timer); controller.current.cancel(id); };
    // The query callback is a static owner adapter; continuation is explicitly loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, normalized, filterFingerprint, disclosed, minimumInput, query]);
  const accept = (option: Option): void => {
    if (option.eligible && identity.current && controller.current.accept_response(identity.current)) {
      onAccept(option); setOpen(false); setDisclosed(false);
    }
  };
  const move = (delta: number): void => {
    if (!open || !options.length) return;
    const current = options.findIndex(option => option.id === active);
    const option = options[Math.max(0, Math.min(options.length - 1, current + delta))];
    if (option) setActive(option.id);
  };
  return <div className="autocomplete">
    <label htmlFor={id}>{label}</label>
    <div className="inline-controls"><input id={id} value={input} role="combobox" aria-expanded={open} aria-controls={id + '-options'}
      aria-autocomplete="list" aria-activedescendant={active ? id + '-option-' + active : undefined}
      onChange={event => {setInput(event.target.value); setDisclosed(false); setOpen(true);}}
      onKeyDown={event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {event.preventDefault(); move(event.key === 'ArrowDown' ? 1 : -1);}
        else if (event.key === 'Escape') {setOpen(false); controller.current.cancel(id);}
        else if (event.key === 'Enter') {event.preventDefault(); const option = options.find(value => value.id === active); if (option) accept(option);}
      }}/><button type="button" aria-label={'Show eligible ' + label} onClick={() => {setDisclosed(true); setOpen(true);}}>Show options</button></div>
    <p role="status">{phase === 'minimum_input' ? `Type at least ${minimumInput} characters.` : phase === 'error' ? 'Options unavailable. Retry the search.' : phase === 'partial' ? 'More results exist. Refine your search.' : phase.replaceAll('_', ' ')}</p>
    {open && <ul id={id + '-options'} role="listbox" data-scroll-owner="y" className="options">
      {options.map(option => <li id={id + '-option-' + option.id} key={option.id} role="option" aria-selected={option.id === active}
        aria-disabled={!option.eligible} onPointerMove={() => setActive(option.id)} onClick={() => accept(option)}>
        {option.label}{!option.eligible && <span> — Unavailable: {option.reason ?? 'Owner eligibility required'}</span>}
      </li>)}
    </ul>}
    {open && cursor !== null && options.length < 50 && <button type="button" disabled={phase === 'loading'} onClick={() => {void load(true);}}>More options</button>}
  </div>;
}
