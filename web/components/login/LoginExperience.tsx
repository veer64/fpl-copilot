"use client";

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { preload } from "react-dom";
import { Gate } from "./Gate";
import { IntroOverlay } from "./IntroOverlay";
import { PlayerStage, PLAYER_IMAGES, type Phase } from "./PlayerStage";
import { SignInCard } from "./SignInCard";
import { setSoundPref, useSoundPref } from "./soundPref";

/** Seconds into the song at which playback starts, so a strong beat lands on the 5.3 s flash (BRIEF: the user tunes it
 *  by ear). Measured in the browser (scripts/audio_onsets.mjs, 2026-11-02): the chorus hits at 41.38 s, so starting at
 *  36.08 s puts it on the flash with the pre-chorus build under the intro. Alternatives: 0 (the piano opening hit lands at
 *  1.36 s, nothing special at 5.3 s) or 45.60 (the 50.90 s hit). */
export const AUDIO_START_OFFSET = 36.08;

export const INTRO_MS = 6200;
const AUDIO_SRC = "/intro/love-me-again.mp3";

export function LoginExperience() {
  // the five images start downloading with the page, so the duo is ready when Kick off is pressed
  for (const href of Object.values(PLAYER_IMAGES)) preload(href, { as: "image" });

  const [phase, setPhase] = useState<Phase>("gate");
  const [audioMissing, setAudioMissing] = useState(false);
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
  const reduced = useRef(false);
  const noHover = useRef(false);

  useEffect(() => {
    reduced.current = !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    noHover.current = !!window.matchMedia?.("(hover: none)").matches;
    // mirror the media query as a class, so the no-animation rules also apply when the page reads it late
    if (reduced.current) stageRef.current?.classList.add("no-motion");
  }, []);

  // --- music: starts on Kick off (a user gesture), loops, ducks to 35 % on the login state, pauses on the gate -------
  const startMusic = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    try {
      a.currentTime = AUDIO_START_OFFSET;
    } catch {
      /* not seekable yet: plays from the start */
    }
    a.volume = 1;
    a.play().catch(() => {});
  }, []);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    if (phase === "login") a.volume = 0.35;
    if (phase === "gate") a.pause();
  }, [phase]);

  useEffect(() => {
    const a = audioRef.current;
    if (a) a.muted = !soundOn;
  }, [soundOn]);

  const toggleSound = () => {
    const next = !soundOn;
    setSoundPref(next);
    const a = audioRef.current;
    if (!a) return;
    a.muted = !next;
    // unmuting on a silent login state (the intro was skipped from the gate) starts the song, quietly
    if (next && a.paused && phase === "login") {
      a.volume = 0.35;
      a.play().catch(() => {});
    }
  };

  // --- phases: gate -> intro (6.2 s) -> login; Skip and Esc go straight to login ----------------------------------------
  const kickOff = () => {
    startMusic();
    setPhase(reduced.current ? "login" : "intro");
  };
  const skip = () => setPhase("login");

  useEffect(() => {
    if (phase !== "intro") return;
    const t = window.setTimeout(() => setPhase("login"), INTRO_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase === "login") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPhase("login");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  // keyboard users: after the intro (or Skip) focus lands on the card, so Tab reaches Continue with Google first
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
    if (reduced.current || noHover.current || phase !== "login") return;
    const r = e.currentTarget.getBoundingClientRect();
    mouse.current = [(e.clientX - r.left) / r.width - 0.5, (e.clientY - r.top) / r.height - 0.5];
    if (!raf.current) raf.current = window.requestAnimationFrame(applyTilt);
  };
  const onLeave = () => {
    if (reduced.current || noHover.current) return;
    mouse.current = [0, 0];
    applyTilt();
  };

  useEffect(() => () => window.cancelAnimationFrame(raf.current), []);

  const soundLabel = soundOn ? "Sound on" : "Sound off";

  return (
    <div ref={stageRef} className={`stage is-${phase}`} data-phase={phase} onMouseMove={onMove} onMouseLeave={onLeave}>
      <div className="bglights" aria-hidden="true" />
      <PlayerStage phase={phase} tiltV={tiltV} tiltH={tiltH} ball={ball} cam={cam} />
      <audio ref={audioRef} src={AUDIO_SRC} preload="auto" loop onError={() => setAudioMissing(true)} />

      {phase === "gate" && <Gate onKickOff={kickOff} onSkip={skip} audioMissing={audioMissing} />}
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
            <SignInCard ref={cardRef} />
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
