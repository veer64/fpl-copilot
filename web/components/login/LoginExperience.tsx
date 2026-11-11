"use client";

import { Suspense, useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { preload } from "react-dom";
import { DELETED_FLAG } from "@/components/account/DeleteAccountDialog";
import { IntroOverlay } from "./IntroOverlay";
import { useReducedMotion } from "./media";
import { PlayerStage, PLAYER_IMAGES, type Phase } from "./PlayerStage";
import { SignInCard } from "./SignInCard";
import { readSoundPref, setSoundPref, useSoundPref } from "./soundPref";

/** Seconds into the song at which playback starts. 0: the song plays from its very beginning (user decision, 2 Nov 2026;
 *  the measured onsets are in eval/reports/w1_login.md if a beat is ever to be placed on the 5.3 s flash). */
export const AUDIO_START_OFFSET = 0;

export const INTRO_MS = 6200;
const AUDIO_SRC = "/intro/love-me-again.mp3";
const INTRO_VOLUME = 1;
const LOGIN_VOLUME = 0.35;

/** /login: the intro starts by itself at 0.0 s (6.2 s, Skip or Esc cut it short), then the login state. Sound is ON by
 *  default: the page tries audio.play() on load; when the browser blocks that, the song starts quietly in the background on
 *  the visitor's first pointerdown / keydown / touchstart / wheel / scroll anywhere -- no prompt. Volume 1 during the
 *  intro, 35 % on login. The header button mutes / unmutes; a remembered mute (localStorage) never auto-starts. */
export function LoginExperience() {
  // the five images start downloading with the page, so the duo is ready as the dissolve begins
  for (const href of Object.values(PLAYER_IMAGES)) preload(href, { as: "image" });

  const [rawPhase, setRawPhase] = useState<Phase>("intro");
  const reduced = useReducedMotion();
  const phase: Phase = reduced && rawPhase === "intro" ? "login" : rawPhase; // reduced motion: no intro at all
  const [musicStarted, setMusicStarted] = useState(false);
  const soundOn = useSoundPref();

  // Prompt W5 (checkpoint C4): arriving from "Delete account" -- the flag the dialog queued in sessionStorage -- skips the
  // intro and its music and shows the green note above the card, once; the flag is cleared, so a reload is a normal visit.
  const [deletedNote, setDeletedNote] = useState(false);
  const fromDelete = useRef(false);
  useEffect(() => {
    let flagged = false;
    try {
      flagged = window.sessionStorage.getItem(DELETED_FLAG) === "1";
      if (flagged) window.sessionStorage.removeItem(DELETED_FLAG);
    } catch {
      flagged = false;
    }
    if (!flagged) return;
    fromDelete.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the one-time note, decided by a flag only the browser holds
    setDeletedNote(true);
    setRawPhase("login");
  }, []);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLElement | null>(null);
  const tiltV = useRef<HTMLDivElement | null>(null);
  const tiltH = useRef<HTMLDivElement | null>(null);
  const ball = useRef<HTMLDivElement | null>(null);
  const cam = useRef<HTMLDivElement | null>(null);
  const mouse = useRef<[number, number]>([0, 0]);
  const raf = useRef(0);
  const noHover = useRef(false);
  const starting = useRef(false);

  useEffect(() => {
    noHover.current = !!window.matchMedia?.("(hover: none)").matches;
  }, []);

  // --- music ----------------------------------------------------------------------------------------------------------
  const startMusic = useCallback((volume: number, manual = false) => {
    const a = audioRef.current;
    if (!a || starting.current) return;
    if (!readSoundPref()) return; // a remembered mute never auto-starts -- checked against storage, not the render
    if (fromDelete.current && !manual) return; // Prompt W5: no music after a deletion unless the button asks for it
    starting.current = true;
    try {
      a.currentTime = AUDIO_START_OFFSET;
    } catch {
      /* not seekable yet: plays from the start anyway */
    }
    a.volume = volume;
    a.muted = false;
    a.play()
      .then(() => setMusicStarted(true))
      .catch(() => {
        starting.current = false; // blocked (no gesture after all): the next interaction tries again
      });
  }, []);

  // on load: try to play at once (allowed when the browser remembers the visitor engaging with the site, or by policy)
  const attempted = useRef(false);
  useEffect(() => {
    if (attempted.current || !soundOn || musicStarted) return;
    attempted.current = true;
    startMusic(phase === "intro" ? INTRO_VOLUME : LOGIN_VOLUME);
  }, [soundOn, musicStarted, phase, startMusic]);

  // blocked: the first interaction anywhere starts the song in the background -- only while not muted
  useEffect(() => {
    if (!soundOn || musicStarted) return;
    const volume = phase === "intro" ? INTRO_VOLUME : LOGIN_VOLUME;
    const onFirst = () => startMusic(volume);
    const opts: AddEventListenerOptions = { capture: true, passive: true };
    const events = ["pointerdown", "keydown", "touchstart", "wheel", "scroll"] as const;
    for (const ev of events) window.addEventListener(ev, onFirst, opts);
    return () => {
      for (const ev of events) window.removeEventListener(ev, onFirst, opts);
    };
  }, [soundOn, musicStarted, phase, startMusic]);

  useEffect(() => {
    const a = audioRef.current;
    if (a && phase === "login") a.volume = LOGIN_VOLUME; // ducks when the login state arrives
  }, [phase]);

  useEffect(() => {
    const a = audioRef.current;
    if (a) a.muted = !soundOn;
  }, [soundOn]);

  // the header button: MUTE / UNMUTE, remembered; unmuting is itself the gesture that starts a song the browser had blocked
  const toggleMute = () => {
    const unmute = !soundOn;
    setSoundPref(unmute);
    const a = audioRef.current;
    if (!a) return;
    a.muted = !unmute;
    if (unmute && a.paused) startMusic(phase === "intro" ? INTRO_VOLUME : LOGIN_VOLUME, true);
  };

  // --- phases: intro (6.2 s, from mount) -> login; Skip and Esc go straight to login ---------------------------------------
  const skip = () => setRawPhase("login");

  useEffect(() => {
    if (phase !== "intro") return;
    stageRef.current?.setAttribute("data-intro-started", String(Math.round(performance.now())));
    const t = window.setTimeout(() => setRawPhase("login"), INTRO_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase === "login") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setRawPhase("login");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  // keyboard users: when the login state arrives, focus lands on the card, so Tab reaches Continue with Google first
  const enteredLogin = useRef(false);
  useEffect(() => {
    if (phase !== "login" || enteredLogin.current) return;
    enteredLogin.current = true;
    const id = window.requestAnimationFrame(() => cardRef.current?.focus({ preventScroll: true }));
    return () => window.cancelAnimationFrame(id);
  }, [phase]);

  // --- mouse parallax: one handler, rAF-throttled; Van Dijk ±3° / 14px, Haaland ±2.5° / 7px, ball 10 / 6, grid −14 ------
  const applyTilt = useCallback(() => {
    raf.current = 0;
    const [mx, my] = mouse.current;
    const ry = mx * 6;
    const rx = -my * 6;
    const t = (k: number, dx: number) =>
      `rotateX(${(rx * k).toFixed(2)}deg) rotateY(${(ry * k).toFixed(2)}deg) translateX(${(mx * dx).toFixed(1)}px)`;
    if (tiltV.current) tiltV.current.style.transform = t(1, 14);
    if (tiltH.current) tiltH.current.style.transform = t(0.85, 7);
    if (ball.current) ball.current.style.transform = `translate(${(mx * 10).toFixed(1)}px,${(my * 6).toFixed(1)}px)`;
    if (cam.current) cam.current.style.transform = `translateX(${(-mx * 14).toFixed(1)}px)`;
  }, []);

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    if (reduced || noHover.current || phase !== "login") return;
    const r = e.currentTarget.getBoundingClientRect();
    mouse.current = [(e.clientX - r.left) / r.width - 0.5, (e.clientY - r.top) / r.height - 0.5];
    if (!raf.current) raf.current = window.requestAnimationFrame(applyTilt);
  };
  const onLeave = () => {
    if (reduced || noHover.current) return;
    mouse.current = [0, 0];
    applyTilt();
  };

  useEffect(() => () => window.cancelAnimationFrame(raf.current), []);

  const muteLabel = soundOn ? "Mute music" : "Unmute music";

  return (
    <div
      ref={stageRef}
      className={`stage is-${phase}${reduced ? " no-motion" : ""}`}
      data-phase={phase}
      data-music={musicStarted ? "playing" : "off"}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
    >
      <div className="bglights" aria-hidden="true" />
      <PlayerStage phase={phase} tiltV={tiltV} tiltH={tiltH} ball={ball} cam={cam} />
      <audio ref={audioRef} src={AUDIO_SRC} preload="auto" loop />

      {phase === "intro" && <IntroOverlay onSkip={skip} />}

      {phase === "login" && (
        <>
          <div className="scrim" aria-hidden="true" />
          <header className="hdr rise">
            <div className="brand">
              {/* eslint-disable-next-line @next/next/no-img-element -- the 28px logo */}
              <img src="/logo.svg" alt="" width={28} height={28} />
              <span>FPL Copilot</span>
            </div>
            <button
              type="button"
              className="sound-btn"
              onClick={toggleMute}
              aria-pressed={!soundOn}
              aria-label={muteLabel}
              title={muteLabel}
              data-testid="sound-toggle"
            >
              {soundOn ? (
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
              <span className="hide-sm">{soundOn ? "Mute" : "Unmute"}</span>
            </button>
          </header>

          <div className="headline rise">
            <span className="eyebrow mono">AI ASSISTANT FOR FPL MANAGERS</span>
            <h1>
              Every decision,
              <br className="br-lg" /> scouted.
            </h1>
          </div>

          <div className="card-wrap">
            <div className="card-col">
              {deletedNote && (
                <div role="status" className="deleted-note" data-testid="deleted-note">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M5 12l5 5L20 7" />
                  </svg>
                  Your account and data were deleted.
                </div>
              )}
              {/* the card reads ?sso= (useSearchParams), which the static page can only do behind Suspense */}
              <Suspense fallback={null}>
                <SignInCard ref={cardRef} />
              </Suspense>
            </div>
          </div>

          <footer className="footer rise">
            <span className="mono ticker">INJURY FLAGS · POINTS PREDICTIONS · FIXTURES · CITED NEWS</span>
            <nav aria-label="Legal" className="legal">
              <a href="/privacy">Privacy</a>
              <a href="/about">About</a>
            </nav>
          </footer>
        </>
      )}
    </div>
  );
}
