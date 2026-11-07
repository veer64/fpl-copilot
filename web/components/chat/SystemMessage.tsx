"use client";

import { leftClock, leftWords } from "@/lib/time";
import type { SystemMsg } from "./types";

/** The four inline system messages (never modals): a daily limit (amber, live countdown to the reset), b 429 (amber,
 *  countdown), c 409 (cyan, "Start a new chat"), d anything else (coral, role="alert", Retry). */
export function SystemMessage({ msg, now, onRetry, onStartNew }: { msg: SystemMsg; now: Date | null; onRetry: (question: string) => void; onStartNew: () => void }) {
  const nowMs = now ? now.getTime() : null;
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
