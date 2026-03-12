import { useEffect, useRef, type RefObject } from 'react';

/**
 * Calls `handler` when a pointerdown event fires outside `ref`.
 * Uses `pointerdown` to handle mouse, touch, and stylus uniformly.
 * Handler is stored in a ref so callers don't need `useCallback`.
 * No-ops when `enabled` is false.
 */
export function useOnClickOutside(
  ref: RefObject<HTMLElement | null>,
  handler: () => void,
  enabled = true,
): void {
  const handlerRef = useRef(handler);
  useEffect(() => { handlerRef.current = handler; });

  useEffect(() => {
    if (!enabled) return;
    const handle = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        handlerRef.current();
      }
    };
    document.addEventListener('pointerdown', handle);
    return () => document.removeEventListener('pointerdown', handle);
  }, [ref, enabled]);
}
