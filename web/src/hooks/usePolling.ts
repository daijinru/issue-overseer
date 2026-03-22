import { useEffect, useRef } from 'react';

/**
 * Generic polling hook.
 * Calls `callback` every `intervalMs` milliseconds while `enabled` is true.
 */
export function usePolling(
  callback: () => void,
  intervalMs: number,
  enabled: boolean,
) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;

    const tick = () => savedCallback.current();
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
}
