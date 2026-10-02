import {useEffect, useRef, useState} from 'react';
import {bindingEqual, DeliberateHold, type HoldBinding, type HoldProviders} from './deliberate-hold';

/** Interaction only: the owning command must consume the LLD-12 proof. */
export function HoldButton({label, binding, available, providers}: {
  label: string; binding: HoldBinding; available: boolean; providers: HoldProviders;
}) {
  const hold = useRef(new DeliberateHold(providers));
  const captured = useRef(binding); const pressed = useRef(false);
  const [progress, setProgress] = useState(0); const [status, setStatus] = useState('Hold continuously for 3 seconds.');
  const cancel = (): void => {
    pressed.current = false;
    if (hold.current.phase === 'submitted') return;
    hold.current.cancel(); setProgress(0); setStatus('Hold cancelled.');
  };
  useEffect(() => {
    if (!bindingEqual(captured.current, binding) || !available) cancel();
    captured.current = binding;
  }, [binding, available]);
  useEffect(() => {
    const interruption = (): void => cancel();
    const visibility = (): void => {if (document.hidden) cancel();};
    window.addEventListener('blur', interruption);
    window.addEventListener('soma-scroll-gesture', interruption);
    document.addEventListener('scroll', interruption, true);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      pressed.current = false; hold.current.cancel();
      window.removeEventListener('blur', interruption);
      window.removeEventListener('soma-scroll-gesture', interruption);
      document.removeEventListener('scroll', interruption, true);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, []);
  const start = async (): Promise<void> => {
    if (pressed.current || !available || hold.current.phase === 'submitted') return;
    pressed.current = true; setStatus('Preparing deliberate action.');
    await hold.current.start(captured.current, available);
    if (!pressed.current) return;
    const frame = (): void => {
      if (!pressed.current) return;
      const value = hold.current.progress(captured.current); setProgress(value);
      if (hold.current.phase !== 'holding') {cancel(); return;}
      setStatus('Keep holding. Release to cancel.');
      if (value === 1) {
        setStatus('Submitting to the action owner.');
        void hold.current.finish(captured.current).then(result => {
          pressed.current = false;
          setStatus(result === null ? 'Action did not complete. Refresh its eligibility.' : 'Action owner accepted the command.');
        });
      } else requestAnimationFrame(frame);
    };
    if (hold.current.phase === 'holding') requestAnimationFrame(frame); else cancel();
  };
  return <div className="deliberate-hold"><button type="button" disabled={!available}
    onPointerDown={event => {if (event.button === 0) {event.currentTarget.setPointerCapture(event.pointerId); void start();}}}
    onPointerUp={cancel} onPointerCancel={cancel} onLostPointerCapture={() => {if (pressed.current) cancel();}} onBlur={() => {if (pressed.current) cancel();}}
    onKeyDown={event => {if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) {event.preventDefault(); void start();}}}
    onKeyUp={event => {if (event.key === ' ' || event.key === 'Enter') {event.preventDefault(); cancel();}}}>
    {label}</button><progress max={1} value={progress} aria-label="Deliberate hold progress"/><p role="status">{status}</p></div>;
}
