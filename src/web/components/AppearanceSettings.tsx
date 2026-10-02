import {useEffect, useRef, useState} from 'react';
import {ownerQuery} from '../data/http';
import {applyAppearance, type Appearance} from '../state/appearance';
type Key = 'ui.appearance_mode' | 'ui.skin_id';
export type AppearanceSetting = Readonly<{setting_key: Key; value: string; revision: number | null;
  source: 'PERSISTED' | 'DEFAULT'; contract_name: string; contract_version: number; semantic_owner: string}>;
export type AppearanceWriter = (request: Readonly<{command_id: string; setting_key: Key; base_revision: number | null; value: string}>) => Promise<AppearanceSetting>;
const modes = ['system', 'light', 'dark'] as const;
const skins = ['soma_core', 'terminal_green', 'terminal_amber', 'terminal_violet'] as const;
function validSetting(value: AppearanceSetting, key: Key): boolean {
  return value?.setting_key === key && value.semantic_owner === 'LLD-10' && value.contract_name === key + '.v1' && value.contract_version === 1
    && (key === 'ui.appearance_mode' ? modes : skins).includes(value.value as never)
    && (value.source === 'DEFAULT' ? value.revision === null : value.source === 'PERSISTED' && Number.isSafeInteger(value.revision) && (value.revision ?? 0) >= 1);
}
function appearance(values: Readonly<Record<Key, AppearanceSetting>>): Appearance {
  return {mode: values['ui.appearance_mode'].value as Appearance['mode'], skin: values['ui.skin_id'].value as Appearance['skin']};
}
/** Each axis uses its own current LLD-02 revision and one owning WriteSetting. */
export function AppearanceSettings({writeSetting = null}: {writeSetting?: AppearanceWriter | null}) {
  const [accepted, setAccepted] = useState<Record<Key, AppearanceSetting> | null>(null);
  const [pending, setPending] = useState(false); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0);
  const [needsRefresh, setNeedsRefresh] = useState(true); const acceptedRef = useRef<Record<Key, AppearanceSetting> | null>(null);
  const alive = useRef(true); const serial = useRef(0);
  useEffect(() => {
    alive.current = true; const abort = new AbortController(); const version = ++serial.current; setError(null); setNeedsRefresh(true);
    void Promise.all((['ui.appearance_mode', 'ui.skin_id'] as const).map(key => ownerQuery<AppearanceSetting>('/api/v1/settings/' + key, abort.signal))).then(values => {
      if (abort.signal.aborted || version !== serial.current) return;
      const mode = values[0], skin = values[1];
      if (!mode || !skin || !validSetting(mode, 'ui.appearance_mode') || !validSetting(skin, 'ui.skin_id')) throw new Error('Invalid registered presentation setting');
      const result = {'ui.appearance_mode': mode, 'ui.skin_id': skin}; acceptedRef.current = result; setAccepted(result); setNeedsRefresh(false); applyAppearance(appearance(result));
    }).catch(() => {if (!abort.signal.aborted && version === serial.current) setError('Appearance settings could not be verified. Retry the owning query.');});
    return () => {alive.current = false; abort.abort(); serial.current++; if (acceptedRef.current) applyAppearance(appearance(acceptedRef.current));};
  }, [retry]);
  const change = async (key: Key, value: string): Promise<void> => {
    if (!accepted || !writeSetting || pending || needsRefresh) return;
    const prior = accepted; const version = ++serial.current;
    setPending(true); setError(null); applyAppearance(appearance({...prior, [key]: {...prior[key], value}}));
    try {
      const saved = await writeSetting({command_id: crypto.randomUUID(), setting_key: key, base_revision: prior[key].revision, value});
      if (!alive.current || version !== serial.current) return;
      if (!validSetting(saved, key)) throw new Error('Invalid accepted presentation setting');
      const next = {...prior, [key]: saved}; acceptedRef.current = next; setAccepted(next); applyAppearance(appearance(next));
    } catch {
      if (alive.current && version === serial.current) {setNeedsRefresh(true); applyAppearance(appearance(prior)); setError('The owner rejected or could not confirm the preference. Accepted appearance has been restored. Refresh before retrying.');}
    } finally {if (alive.current && version === serial.current) setPending(false);}
  };
  return <section aria-label="Appearance preferences"><h2>Appearance</h2>
    {error && <p role="alert">{error}</p>}{!accepted && !error && <p role="status">Loading accepted appearance.</p>}
    <button type="button" data-focus-token="settings:appearance:refresh" disabled={pending} onClick={() => setRetry(retry + 1)}>Refresh appearance</button>
    {!writeSetting && <p role="status">Saving preferences requires the authenticated owner-command binding.</p>}
    {accepted && <><label>Color mode<select value={accepted['ui.appearance_mode'].value} disabled={pending || needsRefresh || !writeSetting} onChange={event => {void change('ui.appearance_mode', event.target.value);}}>
      {modes.map(mode => <option key={mode} value={mode}>{mode === 'system' ? 'System' : mode === 'light' ? 'Light' : 'Dark'}</option>)}</select></label>
      <label>Skin<select value={accepted['ui.skin_id'].value} disabled={pending || needsRefresh || !writeSetting} onChange={event => {void change('ui.skin_id', event.target.value);}}>
        {skins.map(skin => <option key={skin} value={skin}>{({soma_core:'SOMA Core',terminal_green:'Terminal Green',terminal_amber:'Terminal Amber',terminal_violet:'Terminal Violet'})[skin]}</option>)}</select></label></>}
  </section>;
}
