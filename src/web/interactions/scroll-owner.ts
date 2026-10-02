export type Axis = 'x' | 'y';
export function scrollOwner(origin: Element | null, axis: Axis): HTMLElement | null {
  let node: Element | null = origin;
  while (node) {
    if (node instanceof HTMLElement && (node.dataset.scrollOwner === axis || node.dataset.scrollOwner === 'both')) return node;
    node = node.parentElement;
  }
  return null;
}

/** Ownership is fixed at gesture origin; wheel/touch never dispatch selection. */
export function installScrollOwnership(root: HTMLElement, primary: () => HTMLElement | null, onScrollGesture: () => void): () => void {
  let touchOrigin: {x: number; y: number; lastX: number; lastY: number; origin: Element | null; axis: Axis | null; owner: HTMLElement | null} | null = null;
  const wheel = (event: WheelEvent): void => {
    const horizontal = Math.abs(event.deltaX) > Math.abs(event.deltaY);
    const owner = scrollOwner(event.target instanceof Element ? event.target : null, horizontal ? 'x' : 'y');
    onScrollGesture();
    event.preventDefault();
    if (owner) owner.scrollBy({left: horizontal ? event.deltaX : 0, top: horizontal ? 0 : event.deltaY, behavior: 'instant'});
  };
  const key = (event: KeyboardEvent): void => {
    if (!['PageUp', 'PageDown', 'Home', 'End'].includes(event.key) || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
    const owner = scrollOwner(document.activeElement, 'y') ?? primary();
    if (!owner) return;
    event.preventDefault(); onScrollGesture();
    owner.scrollTop = event.key === 'Home' ? 0 : event.key === 'End' ? owner.scrollHeight : owner.scrollTop + owner.clientHeight * (event.key === 'PageDown' ? 1 : -1);
  };
  const start = (event: TouchEvent): void => {
    const touch = event.touches[0];
    if (touch) touchOrigin = {x: touch.clientX, y: touch.clientY, lastX: touch.clientX, lastY: touch.clientY,
      origin: event.target instanceof Element ? event.target : null, axis: null, owner: null};
  };
  const move = (event: TouchEvent): void => {
    const touch = event.touches[0];
    if (!touch || !touchOrigin) return;
    if (touchOrigin.axis === null && Math.hypot(touch.clientX - touchOrigin.x, touch.clientY - touchOrigin.y) >= 8) {
      touchOrigin.axis = Math.abs(touch.clientX - touchOrigin.x) > Math.abs(touch.clientY - touchOrigin.y) ? 'x' : 'y';
      touchOrigin.owner = scrollOwner(touchOrigin.origin, touchOrigin.axis);
    }
    if (touchOrigin.axis === null) return;
    onScrollGesture(); event.preventDefault();
    touchOrigin.owner?.scrollBy({left: touchOrigin.axis === 'x' ? touchOrigin.lastX - touch.clientX : 0,
      top: touchOrigin.axis === 'y' ? touchOrigin.lastY - touch.clientY : 0, behavior: 'instant'});
    touchOrigin.lastX = touch.clientX; touchOrigin.lastY = touch.clientY;
  };
  const end = (): void => { touchOrigin = null; };
  root.addEventListener('wheel', wheel, {passive: false}); root.addEventListener('keydown', key);
  root.addEventListener('touchstart', start, {passive: true}); root.addEventListener('touchmove', move, {passive: false}); root.addEventListener('touchend', end); root.addEventListener('touchcancel', end);
  return () => { root.removeEventListener('wheel', wheel); root.removeEventListener('keydown', key); root.removeEventListener('touchstart', start); root.removeEventListener('touchmove', move); root.removeEventListener('touchend', end); root.removeEventListener('touchcancel', end); };
}
