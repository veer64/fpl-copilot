"use client";

import { Suspense, useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { preload } from "react-dom";
import { IntroOverlay } from "./IntroOverlay";
import { useReducedMotion } from "./media";
import { PlayerStage, PLAYER_IMAGES, type Phase } from "./PlayerStage";
import { SignInCard } from "./SignInCard";
import { setSoundPref, useSoundPref } from "./soundPref";

/** Seconds into the song at which playback starts. 0: the song plays from its very beginning (user decision, 2 Nov 2026;
 *  the measured onsets are in eval/reports/w1_login.md if a beat is ever to be placed on the 5.3 s flash). */
export const AUDIO_START_OFFSET = 0;

export const INTRO_MS = 6200;
const AUDIO_SRC = "/intro/love-me-again.mp3";
const INTRO_VOLUME = 1;
const LOGIN_VOLUME = 0.35;

/** /login: the intro starts by itself at 0.0 s (6.2 s, Skip or Esc cut it short), then the login state. Browsers block
 *  autoplay with sound, so the song starts on the visitor's FIRST pointerdown / keydown / touchstart anywhere -- or on
 *  the "Tap for sound" pill -- at intro volume while the intro runs, else 35 %. A remembered sound-off never auto-starts. */
export function LoginExperience() {
  // the five images start downloading with the page, so the duo is ready as the dissolve begins
  for (const href of Object.values(PLAYER_IMAGES)) preload(href, { as: "image" });

  const [rawPhase, setRawPhase] = useState<Phase>("intro");
  const reduced = useReducedMotion();
  const phase: Phase = reduced && rawPhase === "intro" ? "login" : rawPhase; // reduced motion: no intro at all
  const [musicStarted, setMusicStarted] = useState(false);
  const soundOn = useSoundPref();

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
  const startMusic = useCallback((volume: number) => {
    const a = audioRef.current;
    if (!a || starting.current) return;
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

  // the first interaction anywhere starts the song -- only while the remembered preference is "on"
  useEffect(() => {
    if (!soundOn || musicStarted) return;
    const volume = phase === "intro" ? INTRO_VOLUME : LOGIN_VOLUME;
    const onFirst = () => startMusic(volume);
    const opts: AddEventListenerOptions = { capture: true, passive: true };
    window.addEventListener("pointerdown", onFirst, opts);
    window.addEventListener("keydown", onFirst, opts);
    window.addEventListener("touchstart", onFirst, opts);
    return () => {
      window.removeEventListener("pointerdown", onFirst, opts);
      window.removeEventListener("keydown", onFirst, opts);
      window.removeEventListener("touchstart", onFirst, opts);
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

  const volumeNow = () => (phase === "intro" ? INTRO_VOLUME : LOGIN_VOLUME);

  const toggleSound = () => {
    const next = !soundOn;
    setSoundPref(next);
    const a = audioRef.current;
    if (!a) return;
    a.muted = !next;
    if (next && a.paused) startMusic(volumeNow()); // turning sound on is itself the gesture that starts the song
  };

  const tapForSound = () => {
    if (!soundOn) setSoundPref(true); // an explicit tap overrides a remembered "off"
    startMusic(volumeNow());
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

  const soundLabel = soundOn ? "Sound on" : "Sound off";

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

      {phase === "intro" && <IntroOverlay onSkip={skip} showSoundPill={!musicStarted} onSound={tapForSound} />}

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
              onClick={toggleSound}
              aria-pressed={soundOn}
              aria-label={soundLabel}
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
              <span className="hide-sm">{soundLabel}</span>
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
            {/* the card reads ?sso= (useSearchParams), which the static page can only do behind Suspense */}
            <Suspense fallback={null}>
              <SignInCard ref={cardRef} />
            </Suspense>
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
