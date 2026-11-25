"use client";

import { DraftLimitNote } from "@/components/draft/BuildFlow";
import { leftClock, leftWords } from "@/lib/time";
import type { SystemMsg } from "./types";

/** The four inline system messages (never modals): a daily limit (amber, live countdown to the reset), b 429 (amber,
 *  countdown), c 409 (cyan, "Start a new chat"), d anything else (coral, role="alert", Retry). P3 adds the site's daily
 *  wallet (amber, live countdown, the "everyone" icon) and a refused rebuild (the draft's amber note). */
export function SystemMessage({ msg, now, onRetry, onStartNew }: { msg: SystemMsg; now: Date | null; onRetry: (question: string) => void; onStartNew: () => void }) {
  const nowMs = now ? now.getTime() : null;
  if (msg.variant === "rebuilt") {
    // Prompt W11: the short line after a Rebuild from the team card (a rebuild Yes'd in chat says it in its saved block)
    return (
      <div className="dr-sysline" role="status" data-testid="system-rebuilt">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12a9 9 0 1 1-3-6.7" />
          <path d="M21 4v5h-5" />
        </svg>
        Draft rebuilt from the best picks.
      </div>
    );
  }
  if (msg.variant === "limit") {
    return (
      <div className="ch-sys limit" role="status" data-testid="system-limit">
        <span className="ch-sys-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
        </span>
        <div className="ch-sys-body">
          <div>
            <b>You’ve reached today’s limit.</b>
            <p>
              It resets at 00:00 UTC (in <span className="mono" data-testid="limit-countdown">{now ? leftWords(msg.resetAt, now) : "…"}</span>).
            </p>
          </div>
        </div>
      </div>
    );
  }
  if (msg.variant === "site") {
    // P3: the site's daily wallet for everyone -- the words are the page's (not the server's frozen "in 3 h 12 m"), the
    // countdown is live, and the icon is "everyone" (two people), not the guest's single person
    return (
      <div className="ch-sys limit" role="status" data-testid="system-site">
        <span className="ch-sys-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" data-icon="everyone">
            <circle cx="9" cy="8" r="3.5" />
            <path d="M2.5 20c.8-3.6 3.4-5.6 6.5-5.6s5.7 2 6.5 5.6" />
            <path d="M16 4.7a3.5 3.5 0 0 1 0 6.6M18 14.6c2 .7 3.2 2.6 3.6 5.4" />
          </svg>
        </span>
        <div className="ch-sys-body">
          <div>
            <b>FPL Copilot has reached its daily limit for everyone today.</b>
            <p>
              It resets at 00:00 UTC (in <span className="mono" data-testid="site-countdown">{now ? leftWords(msg.resetAt, now) : "…"}</span>).
            </p>
          </div>
        </div>
      </div>
    );
  }
  if (msg.variant === "draft") return <DraftLimitNote notice={msg.notice} />;
  if (msg.variant === "guest") {
    // W9: a guest's turn refused -- the cap, the shared budget or the switch; the wording is the server's (checkpoint 4)
    return (
      <div className="ch-sys limit" role="status" data-testid="system-guest" data-code={msg.code}>
        <span className="ch-sys-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" />
          </svg>
        </span>
        <div className="ch-sys-body">
          <div>
            <b>{msg.text}</b>
          </div>
        </div>
      </div>
    );
  }
  if (msg.variant === "rate") {
    return (
      <div className="ch-sys rate" role="status" data-testid="system-rate">
        <span className="ch-sys-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 3h12M6 21h12M7 3c0 5 10 5 10 9s-10 4-10 9M17 3c0 5-10 5-10 9" />
          </svg>
        </span>
        <div className="ch-sys-body">
          <div>
            <b>Too many messages — wait a minute.</b>
            <p>
              You can send again in <span className="mono" data-testid="rate-countdown">{nowMs === null ? "…" : leftClock(msg.untilMs, nowMs)}</span>.
            </p>
          </div>
        </div>
      </div>
    );
  }
  if (msg.variant === "team") {
    return (
      <div className="ch-sys team" role="status" data-testid="system-team">
        <span className="ch-sys-ic">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 7h13l-3-3M20 17H7l3 3" />
          </svg>
        </span>
        <div className="ch-sys-body">
          <div>
            <b>Your active team changed — start a new chat</b>
            <p>Answers in this chat would no longer match your team.</p>
          </div>
          <div>
            <button type="button" className="ch-btn-p" onClick={onStartNew} data-testid="start-new-chat">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Start a new chat
            </button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="ch-sys error" role="alert" data-testid="system-error" data-why={msg.why}>
      <span className="ch-sys-ic">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3l9 16H3z" />
          <path d="M12 10v4M12 17h.01" />
        </svg>
      </span>
      <div className="ch-sys-body">
        <div>
          <b>Something went wrong getting that answer.</b>
          <p>Your question is saved — try again.</p>
        </div>
        <div>
          <button type="button" className="ch-btn-s" onClick={() => onRetry(msg.question)} data-testid="retry">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 12a9 9 0 1 1-3-6.7" />
              <path d="M21 4v5h-5" />
            </svg>
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}
