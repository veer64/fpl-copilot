"use client";

import { useEffect, useState } from "react";
import { useAuth, useClerk, useUser } from "@clerk/nextjs";

/** Masks an email the way the project's reports do: a***@g*** -- the first character of each side only. */
export function maskEmail(email: string | null | undefined): string {
  if (!email || !email.includes("@")) return "—";
  const [local, domain] = email.split("@");
  return `${local.charAt(0)}***@${domain.charAt(0)}***`;
}

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

type MeState =
  | { phase: "loading" }
  | { phase: "done"; status: number; body: { user_id?: number; is_admin?: boolean } | string }
  | { phase: "failed"; message: string };

/** The one backend call of Prompt W1: GET /me with the browser's Clerk session token (Authorization: Bearer). The
 *  token names its origin (azp), which the API requires in clerk mode -- the end-to-end check F1a could not run. */
function useMe(): MeState {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [state, setState] = useState<MeState>({ phase: "loading" });

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    const ctrl = new AbortController();
    (async () => {
      try {
        const token = await getToken();
        if (!token) throw new Error("no session token");
        const res = await fetch(`${API_BASE}/me`, { headers: { Authorization: `Bearer ${token}` }, signal: ctrl.signal });
        const text = await res.text();
        let body: { user_id?: number; is_admin?: boolean } | string = text;
        try {
          body = JSON.parse(text) as { user_id?: number; is_admin?: boolean };
        } catch {
          /* not JSON: keep the text */
        }
        setState({ phase: "done", status: res.status, body });
      } catch (err) {
        if (ctrl.signal.aborted) return;
        setState({ phase: "failed", message: err instanceof Error ? err.message : String(err) });
      }
    })();
    return () => ctrl.abort();
  }, [getToken, isLoaded, isSignedIn]);

  return state;
}

export function TeamsPlaceholder() {
  const { user, isLoaded } = useUser();
  const { signOut } = useClerk();
  const me = useMe();
  const email = user?.primaryEmailAddress?.emailAddress;
  const shown =
    me.phase === "done" && typeof me.body === "object"
      ? { user_id: me.body.user_id, is_admin: me.body.is_admin }
      : me.phase === "done"
        ? me.body
        : null;

  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col gap-6 px-4 py-10">
      <header className="flex items-center gap-3 text-fpl-accent">
        {/* eslint-disable-next-line @next/next/no-img-element -- a 28px inline logo, no optimisation wanted */}
        <img src="/logo.svg" alt="" width={28} height={28} />
        <span className="text-[17px] font-semibold text-fpl-text">FPL Copilot</span>
      </header>
      <section className="rounded-2xl border border-fpl-control bg-card p-6">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-fpl-accent-text">Teams · placeholder</p>
        <h1 className="mt-2 text-2xl font-semibold text-fpl-strong">Signed in as {isLoaded ? maskEmail(email) : "…"}</h1>
        <p className="mt-2 text-[15px] leading-[22px] text-fpl-muted">Your FPL teams will live here.</p>
        <button
          type="button"
          onClick={() => signOut({ redirectUrl: "/login" })}
          className="mt-5 h-11 rounded-full border border-fpl-ghost px-5 text-sm text-fpl-secondary hover:border-fpl-ghost-hover hover:text-fpl-text"
        >
          Sign out
        </button>
      </section>
      <section className="rounded-2xl border border-fpl-control bg-card p-6" aria-live="polite">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-fpl-accent-text">
          GET {API_BASE || "(NEXT_PUBLIC_API_BASE unset)"}/me
        </p>
        <p className="mt-2 text-[15px] text-fpl-muted">
          Status:{" "}
          <span className="font-mono text-fpl-text" data-testid="me-status">
            {me.phase === "done" ? me.status : me.phase === "failed" ? `failed (${me.message})` : "…"}
          </span>
        </p>
        <pre className="mt-3 overflow-x-auto rounded-xl bg-black/30 p-4 font-mono text-[13px] leading-5 text-fpl-text" data-testid="me-json">
          {shown === null ? "" : typeof shown === "string" ? shown : JSON.stringify(shown, null, 2)}
        </pre>
      </section>
    </main>
  );
}
