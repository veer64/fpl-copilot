import { useSyncExternalStore } from "react";

/** A media query as a hook (the login page's useReducedMotion pattern): the server renders `false`, the browser's real
 *  answer applies on hydration. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** The brief's breakpoint: at and below 980px everything stacks and the deadline pill leaves the header. */
export const NARROW = "(max-width: 980px)";
export const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
