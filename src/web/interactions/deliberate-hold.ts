export type HoldBinding = Readonly<{actionKind: string; targetType: string; targetId: string; revision: number;
  previewFingerprint: string | null; route: string}>;
export type Challenge = Readonly<{challengeId: string; clientNonce: string; expiresMonotonicMs: number}>;
export type HoldProviders = Readonly<{issue: (binding: HoldBinding, signal: AbortSignal) => Promise<Challenge>;
  complete: (challenge: Challenge, signal: AbortSignal) => Promise<unknown>;
  submit: (binding: HoldBinding, proof: unknown) => Promise<unknown>}>;
export type HoldPhase = 'idle' | 'challenging' | 'holding' | 'completing' | 'submitted' | 'cancelled' | 'error';
// Accepted owner reconciliation: RFC hard-delete is preview plus hold, never plain hold.
const allowed = new Map([['infrastructure.device_reference.promote_new', false], ['tickets.rfc.terminal_cascade.execute', true], ['tickets.rfc.hard_delete', true]]);
export function bindingEqual(a: HoldBinding, b: HoldBinding): boolean {
  return a.actionKind === b.actionKind && a.targetType === b.targetType && a.targetId === b.targetId && a.revision === b.revision &&
    a.previewFingerprint === b.previewFingerprint && a.route === b.route;
}
export class DeliberateHold {
  phase: HoldPhase = 'idle';
  private serial = 0; private abort: AbortController | null = null; private captured: HoldBinding | null = null;
  private challenge: Challenge | null = null; private started = 0;
  constructor(private readonly providers: HoldProviders, private readonly now: () => number = () => performance.now()) {}
  async start(binding: HoldBinding, available: boolean): Promise<void> {
    this.cancel();
    if (!available || !allowed.has(binding.actionKind) || !Number.isSafeInteger(binding.revision) || binding.revision < 1 ||
        !binding.targetType || !binding.targetId || !binding.route ||
        (allowed.get(binding.actionKind) && !/^[0-9a-f]{64}$/u.test(binding.previewFingerprint ?? ''))) return;
    const serial = ++this.serial; this.abort = new AbortController(); this.captured = Object.freeze({...binding}); this.phase = 'challenging';
    try {
      const challenge = await this.providers.issue(this.captured, this.abort.signal);
      if (serial !== this.serial || this.abort.signal.aborted) return;
      if (!challenge.challengeId || !challenge.clientNonce || !Number.isFinite(challenge.expiresMonotonicMs) || challenge.expiresMonotonicMs <= this.now()) {this.cancel(); return;}
      this.challenge = challenge; this.started = this.now(); this.phase = 'holding';
    } catch { if (serial === this.serial) this.phase = 'error'; }
  }
  progress(binding: HoldBinding): number {
    if (this.phase !== 'holding' || !this.captured || !bindingEqual(binding, this.captured) || !this.challenge || this.now() >= this.challenge.expiresMonotonicMs) {if (this.phase === 'holding') this.cancel(); return 0;}
    return Math.min(1, Math.max(0, (this.now() - this.started) / 3000));
  }
  async finish(binding: HoldBinding): Promise<unknown | null> {
    if (this.progress(binding) < 1 || this.phase !== 'holding' || !this.challenge || !this.abort || !this.captured) return null;
    const serial = this.serial; const captured = this.captured; this.phase = 'completing';
    try {
      const proof = await this.providers.complete(this.challenge, this.abort.signal);
      if (serial !== this.serial || this.abort.signal.aborted || !bindingEqual(captured, binding)) return null;
      this.phase = 'submitted'; // freeze before any owning command is invoked
      return await this.providers.submit(captured, proof);
    } catch { if (serial === this.serial) this.phase = 'error'; return null; }
  }
  cancel(): void { this.serial++; this.abort?.abort(); this.abort = null; this.challenge = null; this.captured = null; this.phase = 'cancelled'; }
}
