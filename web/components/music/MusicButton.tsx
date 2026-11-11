"use client";

import { useMusic } from "./MusicProvider";

/** The mute button every header shows next to the account button (Prompt W5b): the login page's mute control, shared. Speaker
 *  while the music plays ("Mute music"), speaker-off otherwise ("Play music"); aria-pressed = paused; the title names the
 *  track. Nothing is rendered when the track list is empty. */
export function MusicButton({ className = "" }: { className?: string }) {
  const m = useMusic();
  if (!m || !m.tracks.length) return null;
  const pressed = !m.playing;
  const label = pressed ? "Play music" : "Mute music";
  const title = m.current ? `Now playing: ${m.current.title} — ${m.current.artist}` : label;
  return (
    <button
      type="button"
      className={`mu-btn${className ? ` ${className}` : ""}`}
      onClick={m.toggle}
      aria-pressed={pressed}
      aria-label={label}
      title={title}
      data-testid="sound-toggle"
      data-playing={m.playing}
      data-track={m.current?.file ?? ""}
    >
      {m.playing ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 9v6h4l5 4V5L8 9H4z" />
          <path d="M16.5 9a4 4 0 0 1 0 6M19.5 6a8 8 0 0 1 0 12" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 9v6h4l5 4V5L8 9H4z" />
          <path d="M17 9.5l5 5M22 9.5l-5 5" />
        </svg>
      )}
    </button>
  );
}
