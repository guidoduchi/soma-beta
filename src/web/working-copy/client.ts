export type RecoveryStatus = 'memory_only' | 'pending' | 'checkpointed' | 'conflict' | 'error';
export type RecoveryCheckpoint = Readonly<{workingCopyId: string; generation: number; contentHash: string}>;
export type RecoveryTransport<T> = (intent: T, expectedGeneration: number, commandId: string, signal: AbortSignal) => Promise<RecoveryCheckpoint>;
/** Recovery is separate from dirty accepted-state intent. A checkpoint is never a domain save. */
export class WorkingCopyClient<T> {
  status: RecoveryStatus = 'memory_only';
  private draft: T | null = null; private editSequence = 0; private generation = 0; private workingCopyId: string | null = null; private lastSuccess = -Infinity;
  private timer: ReturnType<typeof setTimeout> | null = null; private abort: AbortController | null = null; private disposed = false;
  private changedAt = 0;
  constructor(private readonly transport: RecoveryTransport<T>, private readonly changed: () => void,
    private readonly now: () => number = () => performance.now()) {}
  edit(draft: T): void {
    if (this.disposed) return;
    this.draft = structuredClone(draft); this.editSequence++; this.changedAt = this.now();
    // Editing preserves intent; it does not resolve stale owner or generation authority.
    if (this.status !== 'conflict') {this.status = 'memory_only'; this.schedule();}
    this.changed();
  }
  restore(draft: T, checkpoint: RecoveryCheckpoint, freshness: 'CURRENT' | 'STALE' | 'TARGET_MISSING' | 'INDETERMINATE'): void {
    if (this.disposed || this.abort || this.draft !== null) throw new Error('Recovery restore requires an explicit clean edit flow');
    this.validateCheckpoint(checkpoint);
    this.draft = structuredClone(draft); this.generation = checkpoint.generation; this.workingCopyId = checkpoint.workingCopyId; this.editSequence++;
    this.status = freshness === 'CURRENT' ? 'checkpointed' : 'conflict'; this.changed();
  }
  memory(): T | null {return this.draft === null ? null : structuredClone(this.draft);}
  hasUnsavedIntent(): boolean {return this.draft !== null;}
  private validateCheckpoint(result: RecoveryCheckpoint): void {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(result.workingCopyId)
        || !Number.isSafeInteger(result.generation) || result.generation < 1 || !/^[0-9a-f]{64}$/u.test(result.contentHash)) throw new Error('Invalid recovery result');
  }
  private schedule(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    if (this.disposed || this.abort || this.status === 'conflict') return;
    const delay = Math.max(this.changedAt + 5000, this.lastSuccess + 30000) - this.now();
    this.timer = setTimeout(() => {this.timer = null; void this.checkpoint();}, Math.max(0, delay));
  }
  async checkpoint(): Promise<void> {
    if (this.disposed || this.abort || this.draft === null || this.status === 'conflict') return;
    if (this.now() < Math.max(this.changedAt + 5000, this.lastSuccess + 30000)) {this.schedule(); return;}
    const sequence = this.editSequence; const draft = structuredClone(this.draft); const abort = new AbortController();
    this.abort = abort; this.status = 'pending'; this.changed();
    try {
      if (this.disposed || abort.signal.aborted) return;
      const result = await this.transport(draft, this.generation, crypto.randomUUID(), abort.signal);
      if (this.disposed || abort.signal.aborted) return;
      this.validateCheckpoint(result);
      if ((this.workingCopyId !== null && result.workingCopyId !== this.workingCopyId)
          || (this.generation === 0 ? result.generation !== 1 : result.generation !== this.generation && result.generation !== this.generation + 1)) throw new Error('Recovery authority changed unexpectedly');
      this.workingCopyId = result.workingCopyId; this.generation = result.generation; this.lastSuccess = this.now();
      this.status = sequence === this.editSequence ? 'checkpointed' : 'memory_only';
    } catch (error) {
      if (!this.disposed && !abort.signal.aborted) this.status = error instanceof Error && error.message === 'UI_WORKING_COPY_CONFLICT' ? 'conflict' : 'error';
    } finally {
      if (this.abort !== abort) return;
      this.abort = null; if (!this.disposed) this.changed();
      if (!this.disposed && this.status === 'memory_only') this.schedule();
    }
  }
  acceptedSave(): void {if (this.disposed) return; this.abort?.abort(); this.abort = null; this.draft = null; this.editSequence++; this.status = 'memory_only'; if (this.timer !== null) clearTimeout(this.timer); this.timer = null; this.changed();}
  dispose(): void {this.disposed = true; this.abort?.abort(); if (this.timer !== null) clearTimeout(this.timer); this.timer = null;}
}
