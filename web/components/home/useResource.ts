"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useAuth } from "@clerk/nextjs";
import { ApiError, type TokenGetter } from "@/lib/api";

/** One backend call as page state: loading -> ready | error, with `reload`. The loader is a module-level function
 *  (lib/api), so the effect never re-runs for a new closure; every call carries the browser's Clerk session token. */
export type Resource<T> = { status: "loading" } | { status: "error"; error: ApiError } | { status: "ready"; data: T };

export function useResource<T>(load: (t: TokenGetter) => Promise<T>): [Resource<T>, () => void, (data: T) => void] {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    let cancelled = false;
    // Next 16 keeps a left page mounted but hidden (React Activity) and re-runs its effects when it is shown again: the
    // data on it is then stale until this read lands, so the page shows its skeleton rather than the old answer
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a reload that starts with the effect, by design
    setState((s) => (s.status === "loading" ? s : { status: "loading" }));
    load(getToken)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", error: err instanceof ApiError ? err : new ApiError(0, err instanceof Error ? err.message : String(err)) });
      });
    return () => {
      cancelled = true;
    };
  }, [load, getToken, isLoaded, isSignedIn, version]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setVersion((v) => v + 1);
  }, []);
  const set = useCallback((data: T) => setState({ status: "ready", data }), []);
  return [state, reload, set];
}

/** The wall clock, coarse: a snapshot per `everyMs` so the countdown and "time ago" re-render on time, and null during
 *  the server render / hydration (no mismatch: the server has no local clock). */
export function useNow(everyMs = 60_000): Date | null {
  const tick = useSyncExternalStore(
    (cb) => {
      const id = window.setInterval(cb, everyMs);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / everyMs),
    () => 0,
  );
  return tick === 0 ? null : new Date();
}
