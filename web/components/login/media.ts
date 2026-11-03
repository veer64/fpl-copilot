import { useSyncExternalStore } from "react";

/** prefers-reduced-motion as a hook: the server renders "no" and the browser's real answer applies on hydration (no
 *  setState-in-effect, no mismatch). With it on, /login skips the intro and shows the login state at once. */
const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(cb: () => void) {
  const mq = window.matchMedia(QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false);
}
