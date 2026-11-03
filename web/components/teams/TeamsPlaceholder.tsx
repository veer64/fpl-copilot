"use client";

import { useClerk, useUser } from "@clerk/nextjs";

/** Masks an email the way the project's reports do: a***@g*** -- the first character of each side only. */
export function maskEmail(email: string | null | undefined): string {
  if (!email || !email.includes("@")) return "—";
  const [local, domain] = email.split("@");
  return `${local.charAt(0)}***@${domain.charAt(0)}***`;
}

export function TeamsPlaceholder() {
  const { user, isLoaded } = useUser();
  const { signOut } = useClerk();
  const email = user?.primaryEmailAddress?.emailAddress;

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
    </main>
  );
}
