"use client";

const HUD: { at: string; text: string; ready?: boolean }[] = [
  { at: "0.4s", text: "› SYNCING FPL DATA" },
  { at: "1.3s", text: "› INJURY FLAGS · LOADED" },
  { at: "2.2s", text: "› FIXTURES · LOADED" },
  { at: "3.1s", text: "› CLUB NEWS · CITED" },
  { at: "4.2s", text: "› COPILOT READY", ready: true },
];

type Props = { onSkip: () => void; showSoundPill: boolean; onSound: () => void };

/** The 6.2 s intro's chrome: five HUD lines, "Tap for sound" (bottom-left, until the song plays) and Skip intro
 *  (bottom-right). The scene itself animates in PlayerStage. */
export function IntroOverlay({ onSkip, showSoundPill, onSound }: Props) {
  return (
    <>
      <div className="hud mono" aria-hidden="true" data-testid="hud">
        {HUD.map((h) => (
          <span key={h.text} className="hud-line" style={{ animationDelay: h.at, color: h.ready ? "#E8F6FF" : undefined }}>
            {h.text}
          </span>
        ))}
      </div>
      {showSoundPill && (
        <button type="button" className="intro-sound" onClick={onSound} aria-label="Tap for sound" data-testid="tap-for-sound">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4 9v6h4l5 4V5L8 9H4z" />
            <path d="M16.5 9a4 4 0 0 1 0 6M19.5 6a8 8 0 0 1 0 12" />
          </svg>
          Tap for sound
        </button>
      )}
      <button type="button" className="intro-skip" onClick={onSkip} data-testid="skip-intro">
        Skip intro
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 6l6 6-6 6M13 6l6 6-6 6" />
        </svg>
      </button>
    </>
  );
}
