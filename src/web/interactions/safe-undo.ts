import type {RecordRef} from '../state/ui-store.js';
export type InversePreview = Readonly<{state: 'AVAILABLE' | 'BLOCKED' | 'STALE' | 'INDETERMINATE'; fingerprint: string | null; reason: string | null}>;
export type Opportunity = Readonly<{id: string; owner: string; inverseKind: string; actionResultRef: string; target: RecordRef; postRevision: string}>;
export type SafeInverse = Readonly<{commandContract: string; preview: (opportunity: Opportunity) => Promise<InversePreview>;
  build: (opportunity: Opportunity, fingerprint: string) => Promise<unknown>; submit: (commandContract: string, request: unknown) => Promise<unknown>}>;
export class SafeUndo {
  private readonly opportunities = new Map<string, Opportunity>(); private readonly active = new Set<string>();
  private readonly registry: ReadonlyMap<string, SafeInverse>;
  constructor(registry: ReadonlyMap<string, SafeInverse>) { this.registry = new Map(Array.from(registry, ([key, provider]) => [key, Object.freeze({...provider})])); }
  private provider(opportunity: Opportunity): SafeInverse | undefined {return this.registry.get(opportunity.owner + ':' + opportunity.inverseKind);}
  remember(opportunity: Opportunity): boolean {
    if (!this.provider(opportunity)) return false;
    if (!opportunity.id || !opportunity.actionResultRef || !opportunity.postRevision || this.opportunities.has(opportunity.id)) return false;
    if (this.opportunities.size === 20) {
      const oldest = Array.from(this.opportunities.keys()).find(id => !this.active.has(id));
      if (!oldest) return false;
      this.opportunities.delete(oldest);
    }
    this.opportunities.set(opportunity.id, Object.freeze({...opportunity, target: Object.freeze({...opportunity.target})})); return true;
  }
  list(): readonly Opportunity[] {return Array.from(this.opportunities.values());}
  async availability(id: string): Promise<InversePreview> {
    const opportunity = this.opportunities.get(id); const provider = opportunity && this.provider(opportunity);
    if (!opportunity || !provider) return {state: 'INDETERMINATE', fingerprint: null, reason: 'No approved safe inverse is registered.'};
    try {return await provider.preview(opportunity);} catch {return {state: 'INDETERMINATE', fingerprint: null, reason: 'Inverse availability could not be verified.'};}
  }
  async execute(id: string): Promise<boolean> {
    if (this.active.has(id)) return false;
    const opportunity = this.opportunities.get(id); const provider = opportunity && this.provider(opportunity);
    if (!opportunity || !provider) return false;
    this.active.add(id);
    try {
      const preview = await this.availability(id);
      if (preview.state !== 'AVAILABLE' || !/^[0-9a-f]{64}$/u.test(preview.fingerprint ?? '')) return false;
      const request = await provider.build(opportunity, preview.fingerprint!);
      await provider.submit(provider.commandContract, request);
      this.opportunities.delete(id); return true;
    } catch {return false;} finally {this.active.delete(id);}
  }
}
