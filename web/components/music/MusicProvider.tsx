"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { readSoundPref, setSoundPref, useSoundPref } from "@/components/login/soundPref";
import { MUSIC_TRACKS, trackUrl, type MusicTrack } from "@/lib/music-tracks";

/** The site's background music (Prompt W5b, 10 Nov 2026): ONE <audio> element owned here, in the root layout, so a track keeps
 *  playing across every client-side navigation (Login -> Home -> Chat -> About -> Privacy) without restarting.
 *
 *  - Shuffle: a visit starts on a random track that is NOT the one the previous visit started on (localStorage LAST_KEY); a
 *    finished track crosses straight to the next of a shuffled queue; every track plays before any repeats; never the same
 *    track twice in a row across a reshuffle.
 *  - Full page loads (the Google sign-in redirect, a refresh, a sign-out): {track, position} saved in sessionStorage every
 *    SAVE_EVERY_MS and on pagehide; after a reload the same track resumes within a couple of seconds when not muted.
 *  - Autoplay blocked (NotAllowedError): no error, no prompt -- the first pointerdown / keydown / touchstart anywhere starts it.
 *  - Mute = paused with the source dropped (nothing downloads while muted); unmuting puts the same track back at its position.
 *    The choice lives in the existing "fpl-sound" key (login's mute), so earlier visitors' choice carries over.
 *  - Volume: the login page's 0.35 everywhere; the login intro asks for 1.0 for its 6.2 s (setLevel), with a ~1.5 s fade-in at
 *    every start. Muted = paused (the <audio> is also muted, as the login page's tests expect).
 *  - An empty track list: no element, no button, nothing stored. */

export const LAST_KEY = "fpl.music.last";
export const RESUME_KEY = "fpl.music.resume";
export const NORMAL_VOLUME = 0.35;
export const INTRO_VOLUME = 1;
export const FADE_MS = 1500;
export const SAVE_EVERY_MS = 3000;

export type MusicLevel = "intro" | "normal";
export type Music = {
  tracks: readonly MusicTrack[];
  current: MusicTrack | null;
  playing: boolean;
  soundOn: boolean;
  /** the button: playing -> mute; else -> play (a user gesture, so autoplay rules allow it) */
  toggle: () => void;
  /** this visit must not start on its own (the Login page after an account deletion); paused if it already plays */
  holdThisVisit: () => void;
  setLevel: (level: MusicLevel) => void;
};

const MusicContext = createContext<Music | null>(null);

export function useMusic(): Music | null {
  return useContext(MusicContext);
}

function shuffled<T>(list: readonly T[]): T[] {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** A new play order whose first track is not `avoidFirst` (when there is a choice). */
export function makeQueue(tracks: readonly MusicTrack[], avoidFirst: string | null): MusicTrack[] {
  const q = shuffled(tracks);
  if (q.length > 1 && avoidFirst && q[0].file === avoidFirst) {
    const j = 1 + Math.floor(Math.random() * (q.length - 1));
    [q[0], q[j]] = [q[j], q[0]];
  }
  return q;
}

type Saved = { file: string; pos: number; at: number };

function readResume(tracks: readonly MusicTrack[]): Saved | null {
  try {
    const raw = window.sessionStorage.getItem(RESUME_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Saved;
    if (!s || typeof s.file !== "string" || !tracks.some((t) => t.file === s.file)) return null;
    return { file: s.file, pos: Number.isFinite(s.pos) ? Math.max(0, s.pos) : 0, at: s.at };
  } catch {
    return null;
  }
}

export function MusicProvider({ children }: { children: ReactNode }) {
  const tracks = MUSIC_TRACKS;
  const soundOn = useSoundPref();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const queue = useRef<MusicTrack[]>([]);
  const index = useRef(0);
  const held = useRef(false);
  const level = useRef<MusicLevel>("normal");
  const fade = useRef<number | null>(null);
  const lastSave = useRef(0);
  const armed = useRef(false);
  const [current, setCurrent] = useState<MusicTrack | null>(null);
  const [playing, setPlaying] = useState(false);

  const target = () => (level.current === "intro" ? INTRO_VOLUME : NORMAL_VOLUME);

  const stopFade = () => {
    if (fade.current !== null) {
      window.clearInterval(fade.current);
      fade.current = null;
    }
  };

  // a timer, not requestAnimationFrame: the fade must finish even when the tab is not being painted
  const fadeIn = useCallback((a: HTMLAudioElement) => {
    stopFade();
    const t0 = Date.now();
    a.volume = 0;
    fade.current = window.setInterval(() => {
      const k = Math.min(1, (Date.now() - t0) / FADE_MS);
      a.volume = target() * k;
      if (k >= 1) stopFade();
    }, 50);
  }, []);

  const save = useCallback((a: HTMLAudioElement, track: MusicTrack | null) => {
    if (!track) return;
    try {
      window.sessionStorage.setItem(RESUME_KEY, JSON.stringify({ file: track.file, pos: a.currentTime, at: Date.now() } satisfies Saved));
    } catch {
      /* no storage */
    }
  }, []);

  /** Load `track` into the element at `pos` and try to play (fading in). A refusal arms the first-interaction start. */
  const start = useCallback(
    (track: MusicTrack, pos: number, withFade: boolean) => {
      const a = audioRef.current;
      if (!a) return;
      setCurrent(track);
      const url = trackUrl(track);
      if (!a.src.endsWith(url)) {
        a.src = url;
        a.load();
      }
      try {
        a.currentTime = pos;
      } catch {
        /* not seekable yet: starts from 0 */
      }
      a.muted = false;
      if (withFade) fadeIn(a);
      else {
        stopFade();
        a.volume = target();
      }
      const p = a.play();
      if (p && typeof p.catch === "function") {
        p.catch(() => {
          if (armed.current) return;
          armed.current = true;
          const onFirst = () => {
            if (!readSoundPref() || held.current) return;
            const el = audioRef.current;
            if (!el || !el.paused) return;
            el.play().catch(() => undefined);
          };
          const opts: AddEventListenerOptions = { capture: true, passive: true, once: true };
          for (const ev of ["pointerdown", "keydown", "touchstart"] as const) window.addEventListener(ev, onFirst, opts);
        });
      }
    },
    [fadeIn],
  );

  const advance = useCallback(() => {
    if (!tracks.length) return;
    const done = queue.current[index.current] ?? current;
    index.current += 1;
    if (index.current >= queue.current.length) {
      queue.current = makeQueue(tracks, done?.file ?? null);
      index.current = 0;
    }
    const next = queue.current[index.current];
    start(next, 0, false); // the next track crosses straight in
  }, [tracks, current, start]);

  // the element's events
  useEffect(() => {
    const a = audioRef.current;
    if (!a || !tracks.length) return;
    const onPlaying = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => advance();
    const onTime = () => {
      const now = performance.now();
      if (now - lastSave.current < SAVE_EVERY_MS) return;
      lastSave.current = now;
      save(a, queue.current[index.current] ?? null);
    };
    const onHide = () => save(a, queue.current[index.current] ?? null);
    a.addEventListener("playing", onPlaying);
    a.addEventListener("pause", onPause);
    a.addEventListener("ended", onEnded);
    a.addEventListener("timeupdate", onTime);
    window.addEventListener("pagehide", onHide);
    return () => {
      a.removeEventListener("playing", onPlaying);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("ended", onEnded);
      a.removeEventListener("timeupdate", onTime);
      window.removeEventListener("pagehide", onHide);
    };
  }, [tracks, advance, save]);

  // the visit's start: resume the same track after a reload, else a fresh shuffled queue avoiding the previous visit's start
  const started = useRef(false);
  useEffect(() => {
    if (started.current || !tracks.length) return;
    started.current = true;
    const resume = readResume(tracks);
    let last: string | null = null;
    try {
      last = window.localStorage.getItem(LAST_KEY);
    } catch {
      last = null;
    }
    if (resume) {
      queue.current = makeQueue(tracks, null);
      const i = queue.current.findIndex((t) => t.file === resume.file);
      if (i > 0) [queue.current[0], queue.current[i]] = [queue.current[i], queue.current[0]];
      index.current = 0;
    } else {
      queue.current = makeQueue(tracks, last);
      index.current = 0;
      try {
        window.localStorage.setItem(LAST_KEY, queue.current[0].file);
      } catch {
        /* no storage */
      }
    }
    const first = queue.current[0];
    setCurrent(first);
    if (!readSoundPref() || held.current) return; // a remembered mute never auto-starts; a held visit neither
    start(first, resume ? resume.pos : 0, true);
  }, [tracks, start]);

  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a || !tracks.length) return;
    const track = queue.current[index.current] ?? current;
    if (!a.paused) {
      // mute = pause + drop the source (no download while muted); the position is kept for the unmute
      save(a, track);
      setSoundPref(false);
      stopFade();
      a.pause();
      a.muted = true;
      a.removeAttribute("src");
      a.load();
      setPlaying(false);
      return;
    }
    held.current = false;
    setSoundPref(true);
    const resume = readResume(tracks);
    if (track) start(track, resume && resume.file === track.file ? resume.pos : 0, true);
  }, [tracks, current, save, start]);

  const holdThisVisit = useCallback(() => {
    held.current = true;
    const a = audioRef.current;
    if (a && !a.paused) {
      save(a, queue.current[index.current] ?? null);
      stopFade();
      a.pause();
    }
  }, [save]);

  const setLevel = useCallback((next: MusicLevel) => {
    level.current = next;
    const a = audioRef.current;
    if (a && fade.current === null) a.volume = target();
  }, []);

  const value = useMemo<Music>(() => ({ tracks, current, playing, soundOn, toggle, holdThisVisit, setLevel }), [tracks, current, playing, soundOn, toggle, holdThisVisit, setLevel]);

  return (
    <MusicContext.Provider value={value}>
      {children}
      {tracks.length > 0 && (
        <audio ref={audioRef} preload="none" data-testid="site-audio" data-track={current?.file ?? ""} data-playing={playing} aria-hidden="true" />
      )}
    </MusicContext.Provider>
  );
}
