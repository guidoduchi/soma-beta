import {useEffect, useRef, useState} from 'react';
import {filterFingerprint, QueryController, type QueryTicket} from '../data/query-controller';
import {validChronology, type ChronologyV1} from '../data/communications-contracts';

export type CommunicationSummary = Readonly<{target_type: string; target_id: string; received_count: number; sent_count: number;
  unknown_count: number; last_interaction: ChronologyV1; last_direction: 'RECEIVED' | 'SENT' | 'MIXED' | 'UNKNOWN'; pending_proposals: number;
  coverage_state: string; warnings: readonly string[]; body_navigation_available: boolean}>;
export type CommunicationMessage = Readonly<{communication_id: string; subject: string | null; direction: string; content_state: string;
  chronology: ChronologyV1}>;
export type CommunicationProjection = Readonly<{summary: CommunicationSummary;
  recent_messages: Readonly<{items: readonly CommunicationMessage[]; next_cursor: unknown | null}>; terminal_frozen: boolean; warnings: readonly string[]}>;
export type PanelQuery = (targetType: string, targetId: string, cursor: unknown | null, limit: 50, signal: AbortSignal) => Promise<CommunicationProjection>;

/** Query renders canonical owner projection, never copies message bodies into UI intent. */
export function CommunicationPanel({targetType, targetId, query, openMessage}: {
  targetType: string; targetId: string; query: PanelQuery; openMessage: (id: string) => void;
}) {
  const controller = useRef(new QueryController()); const [projection, setProjection] = useState<CommunicationProjection | null>(null);
  const loadSequence = useRef(0);
  const acceptedSource = useRef<{targetType: string; targetId: string; query: PanelQuery} | null>(null);
  const [phase, setPhase] = useState<'loading' | 'accepted' | 'error'>('loading'); const [retry, setRetry] = useState(0);
  const load = async (cursor: unknown | null): Promise<void> => {
    const sequence = ++loadSequence.current;
    controller.current.cancel('communication-panel'); setPhase('loading');
    let ticket: QueryTicket | undefined;
    try {
      const fingerprint = await filterFingerprint({targetType, targetId, cursor: JSON.stringify(cursor), limit: '50'});
      if (sequence !== loadSequence.current) return;
      ticket = controller.current.start('communication-panel', targetId, fingerprint);
      const value = await query(targetType, targetId, cursor, 50, ticket.signal);
      if (!controller.current.accept_response(ticket.identity)) return;
      if (!value.summary || !value.recent_messages || !Array.isArray(value.recent_messages.items)
          || value.summary.target_type !== targetType || value.summary.target_id !== targetId || value.recent_messages.items.length > 50
          || value.recent_messages.items.some(item => typeof item.communication_id !== 'string' || !item.communication_id)
          || new Set(value.recent_messages.items.map(item => item.communication_id)).size !== value.recent_messages.items.length
          || [value.summary.received_count, value.summary.sent_count, value.summary.unknown_count, value.summary.pending_proposals]
            .some(count => !Number.isSafeInteger(count) || count < 0)
          || !['RECEIVED', 'SENT', 'MIXED', 'UNKNOWN'].includes(value.summary.last_direction ?? '')
          || !validChronology(value.summary.last_interaction) || value.recent_messages.items.some(item => !validChronology(item.chronology))
          || typeof value.summary.body_navigation_available !== 'boolean' || typeof value.terminal_frozen !== 'boolean'
          || !Array.isArray(value.summary.warnings) || !Array.isArray(value.warnings)
          || [...value.summary.warnings, ...value.warnings].some(warning => typeof warning !== 'string')
          || !Object.hasOwn(value.recent_messages, 'next_cursor')) throw new Error('Invalid canonical panel projection');
      acceptedSource.current = {targetType, targetId, query};
      setProjection(value); setPhase('accepted');
    } catch {if (sequence === loadSequence.current && (!ticket || controller.current.accept_response(ticket.identity))) setPhase('error');}
  };
  useEffect(() => {setProjection(null); void load(null); return () => {
    ++loadSequence.current; controller.current.cancel('communication-panel');
  };}, [targetType, targetId, query, retry]);
  const currentProjection = acceptedSource.current?.targetType === targetType && acceptedSource.current.targetId === targetId
    && acceptedSource.current.query === query ? projection : null;
  const warnings = currentProjection ? [...new Set([...currentProjection.summary.warnings, ...currentProjection.warnings])] : [];
  return <section aria-label="Canonical communication evidence"><h2>Communications</h2>
    {phase === 'loading' && <p role="status">Loading communication evidence.</p>}
    {phase === 'error' && <><p role="alert">Communication evidence is unavailable. Operational work remains available; retained evidence may be stale.</p>
      <button type="button" onClick={() => setRetry(retry + 1)}>Retry communications</button></>}
    {currentProjection && <><p>Coverage: {currentProjection.summary.coverage_state}</p>
      <p>Received: {currentProjection.summary.received_count}. Sent: {currentProjection.summary.sent_count}. Unknown direction: {currentProjection.summary.unknown_count}.</p>
      <p>Pending proposals: {currentProjection.summary.pending_proposals}</p>
      <p>Last direction: {currentProjection.summary.last_direction}</p>
      <p>Last supported interaction: {currentProjection.summary.last_interaction.known
        ? `UTC epoch seconds ${currentProjection.summary.last_interaction.utc_epoch_seconds}; source ${currentProjection.summary.last_interaction.source_kind}`
        : 'Unknown'}</p>
      {currentProjection.terminal_frozen && <p>Historical terminal summary. Content navigation follows retained evidence availability.</p>}
      {warnings.map(warning => <p className="warning" key={warning}>{warning}</p>)}
      {currentProjection.recent_messages.items.length === 0 && <p>No linked messages in this page. Coverage determines whether this is complete.</p>}
      <ul>{currentProjection.recent_messages.items.map(message => <li key={message.communication_id}>
        <span>{message.subject ?? 'Content unavailable'} — {message.direction}</span>
        {!currentProjection.terminal_frozen && currentProjection.summary.body_navigation_available && message.content_state === 'RETAINED' && phase === 'accepted' &&
          <button type="button" onClick={() => openMessage(message.communication_id)}>Open canonical message</button>}
      </li>)}</ul>
      {currentProjection.recent_messages.next_cursor !== null && <button type="button" disabled={phase !== 'accepted'}
        onClick={() => {void load(currentProjection.recent_messages.next_cursor);}}>Next messages</button>}
    </>}
  </section>;
}
