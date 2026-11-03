"use client";

const HUD: { at: string; text: string; ready?: boolean }[] = [
  { at: "0.4s", text: "› SYNCING FPL DATA" },
  { at: "1.3s", text: "› INJURY FLAGS · LOADED" },
  { at: "2.2s", text: "› FIXTURES · LOADED" },
  { at: "3.1s", text: "› CLUB NEWS · CITED" },
  { at: "4.2s", text: "› COPILOT READY", ready: true },
];

/** The 6.2 s intro's chrome: five HUD lines and Skip intro (bottom-right). The scene itself animates in PlayerStage. */
export function IntroOverlay({ onSkip }: { onSkip: () => void }) {
  return (
    <>
      <div className="hud mono" aria-hidden="true" data-testid="hud">
        {HUD.map((h) => (
          <span key={h.text} className="hud-line" style={{ animationDelay: h.at, color: h.ready ? "#E8F6FF" : undefined }}>
            {h.text}
          </span>
        ))}
      </div>
      <button type="button" className="intro-skip" onClick={onSkip} data-testid="skip-intro">
        Skip intro
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 6l6 6-6 6M13 6l6 6-6 6" />
        </svg>
      </button>
    </>
  );
}
