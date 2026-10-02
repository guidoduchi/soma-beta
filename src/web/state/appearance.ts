export type Appearance = Readonly<{mode: 'system' | 'light' | 'dark'; skin: 'soma_core' | 'terminal_green' | 'terminal_amber' | 'terminal_violet'}>;
export function validAppearance(value: Appearance): boolean {
  return ['system', 'light', 'dark'].includes(value.mode) && ['soma_core', 'terminal_green', 'terminal_amber', 'terminal_violet'].includes(value.skin);
}
export class AppearanceController {
  private accepted: Appearance; private version = 0;
  constructor(initial: Appearance, private readonly apply: (value: Appearance) => void) {
    if (!validAppearance(initial)) throw new Error('Unregistered appearance');
    this.accepted = initial; apply(initial);
  }
  async previewAndSave(value: Appearance, ownerSave: (value: Appearance) => Promise<Appearance>): Promise<boolean> {
    if (!validAppearance(value)) return false;
    const version = ++this.version; this.apply(value);
    try {
      const saved = await ownerSave(value);
      if (!validAppearance(saved)) throw new Error('Invalid appearance result');
      if (version === this.version) {this.accepted = saved; this.apply(saved);}
      return true;
    } catch {if (version === this.version) this.apply(this.accepted); return false;}
  }
}
let systemListener: {media: MediaQueryList; changed: () => void} | null = null;
export function applyAppearance(value: Appearance): void {
  if (!validAppearance(value)) throw new Error('Unregistered appearance');
  document.documentElement.dataset.mode = value.mode === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : value.mode;
  document.documentElement.dataset.skin = value.skin;
  if (systemListener) systemListener.media.removeEventListener('change', systemListener.changed);
  systemListener = null;
  if (value.mode === 'system') {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const changed = (): void => {document.documentElement.dataset.mode = media.matches ? 'dark' : 'light';};
    systemListener = {media, changed}; media.addEventListener('change', changed);
  }
}
export function observeSystemAppearance(current: () => Appearance): () => void {
  const media = matchMedia('(prefers-color-scheme: dark)');
  const changed = (): void => {const value = current(); if (value.mode === 'system') applyAppearance(value);};
  media.addEventListener('change', changed);
  return () => media.removeEventListener('change', changed);
}
