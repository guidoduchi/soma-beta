import {useEffect, useState, type RefObject} from 'react';
export type ResponsiveClass = 'narrow' | 'standard' | 'wide';
export function classifyContainer(width: number): ResponsiveClass {
  if (!Number.isFinite(width) || width < 0) throw new Error('Invalid container measurement');
  return width < 720 ? 'narrow' : width < 1200 ? 'standard' : 'wide';
}
export function useContainerWidth(element: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = element.current;
    if (!node) return;
    if (!('ResizeObserver' in window)) {setWidth(node.getBoundingClientRect().width); return;}
    const observer = new ResizeObserver(entries => { const entry = entries[0]; if (entry) setWidth(entry.contentRect.width); });
    observer.observe(node); return () => observer.disconnect();
  }, [element]);
  return width;
}
export function unsupportedCapabilities(): readonly string[] {
  const checks: Record<string, boolean> = {
    'container queries': typeof CSS !== 'undefined' && CSS.supports('container-type', 'inline-size'),
    'overscroll containment': typeof CSS !== 'undefined' && CSS.supports('overscroll-behavior', 'contain'),
    'pointer events': 'PointerEvent' in window, 'container observation': 'ResizeObserver' in window,
    'request cancellation': 'AbortController' in window, 'navigation history': 'pushState' in history,
    'modal isolation': 'inert' in HTMLElement.prototype,
    'reduced motion': typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').media !== 'not all',
    'forced colors': typeof matchMedia === 'function' && matchMedia('(forced-colors: active)').media !== 'not all',
  };
  return Object.entries(checks).filter(([, supported]) => !supported).map(([name]) => name);
}
