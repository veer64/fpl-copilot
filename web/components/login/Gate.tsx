"use client";

type Props = { onKickOff: () => void; onSkip: () => void; audioMissing: boolean };

/** The gate shown on every visit: the brand, Kick off (starts the music and the intro), Skip intro. */
export function Gate({ onKickOff, onSkip, audioMissing }: Props) {
  return (
    <div className="gate rise" data-testid="gate">
      <div className="gate-brand">
        <svg width="34" height="34" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
          <path d="M14 2 L25 8.5 V19.5 L14 26 L3 19.5 V8.5 Z" />
          <path d="M9 17 L14 11 L19 17" />
        </svg>
        <span className="mono">FPL COPILOT</span>
      </div>
      <button type="button" className="kick" onClick={onKickOff} data-testid="kick-off">
        <span className="ring" aria-hidden="true" />
        <span className="ring" aria-hidden="true" style={{ animationDelay: "1.2s" }} />
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M7 4.5v15l13-7.5z" />
        </svg>
        <span className="mono">KICK OFF</span>
      </button>
      <div className="gate-lines">
        <p className="gate-lead">Sound on — best with headphones.</p>
        <p className="gate-music mono">MUSIC · LOVE ME AGAIN — JOHN NEWMAN{audioMissing ? " · [ADD MP3]" : ""}</p>
      </div>
      <button type="button" className="ghost-btn" onClick={onSkip} data-testid="skip-gate">
        Skip intro
      </button>
    </div>
  );
}
