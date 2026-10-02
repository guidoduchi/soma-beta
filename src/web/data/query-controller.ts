export type QueryIdentity = Readonly<{query_id: string; surface_id: string; normalized_input: string; filter_fingerprint: string; sequence: number}>;
export type QueryTicket = Readonly<{identity: QueryIdentity; signal: AbortSignal}>;
export class QueryController {
  private readonly current = new Map<string, {ticket: QueryTicket; abort: AbortController}>();
  private readonly sequence = new Map<string, number>();
  start(surface_id: string, normalized_input: string, filter_fingerprint: string): QueryTicket {
    this.cancel(surface_id);
    const sequence = (this.sequence.get(surface_id) ?? 0) + 1;
    this.sequence.set(surface_id, sequence);
    const abort = new AbortController();
    const ticket = {identity: Object.freeze({query_id: crypto.randomUUID(), surface_id, normalized_input, filter_fingerprint, sequence}), signal: abort.signal};
    this.current.set(surface_id, {ticket, abort});
    return ticket;
  }
  accept_response(identity: QueryIdentity): boolean {
    const value = this.current.get(identity.surface_id);
    if (!value || value.ticket.signal.aborted) return false;
    const current = value.ticket.identity;
    return current.query_id === identity.query_id && current.sequence === identity.sequence &&
      current.normalized_input === identity.normalized_input && current.filter_fingerprint === identity.filter_fingerprint;
  }
  cancel(surface_id: string): void { this.current.get(surface_id)?.abort.abort(); this.current.delete(surface_id); }
}

export async function filterFingerprint(value: Readonly<Record<string, string>>): Promise<string> {
  const compare = (a: string, b: string): number => {
    const left = Array.from(a, char => char.codePointAt(0) ?? 0), right = Array.from(b, char => char.codePointAt(0) ?? 0);
    for (let i = 0; i < Math.min(left.length, right.length); i++) {
      const difference = (left[i] ?? 0) - (right[i] ?? 0); if (difference) return difference;
    }
    return left.length - right.length;
  };
  const canonical = '{' + Object.entries(value).sort(([a], [b]) => compare(a, b)).map(([key, item]) => JSON.stringify(key) + ':' + JSON.stringify(item)).join(',') + '}';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}
