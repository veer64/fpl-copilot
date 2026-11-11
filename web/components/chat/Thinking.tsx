"use client";

import { useEffect, useState } from "react";
import { nextWordIndex, spinnerWords } from "@/lib/spinner-words";
import { REDUCED_MOTION, useMediaQuery } from "@/lib/useMediaQuery";

const ROTATE_MS = 3000;
const STATUS_MS = 5000;

/** The thinking row: the ring, one spinner word (random first, the next every ~3 s with a short fade/slide, never the same
 *  twice in a row; under reduced motion one word and no spin), the seconds. Screen readers hear only "Thinking, {n}
 *  seconds" (role="status", refreshed every 5 s); the word is aria-hidden. */
export function Thinking({ startedAt, resumed = false }: { startedAt: number; resumed?: boolean }) {
  const reduced = useMediaQuery(REDUCED_MOTION);
  const words = spinnerWords();
  const [idx, setIdx] = useState<number>(() => nextWordIndex(null, words.length));
  const [tick, setTick] = useState(0);
  const [secs, setSecs] = useState(0);
  const [statusSecs, setStatusSecs] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => setSecs(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);
  useEffect(() => {
    const id = window.setInterval(() => setStatusSecs(Math.floor((Date.now() - startedAt) / 1000)), STATUS_MS);
    return () => window.clearInterval(id);
  }, [startedAt]);
  useEffect(() => {
    if (reduced || words.length <= 1) return;
    const id = window.setInterval(() => {
      setIdx((i) => nextWordIndex(i, words.length));
      setTick((t) => t + 1);
    }, ROTATE_MS);
    return () => window.clearInterval(id);
  }, [reduced, words.length]);

  return (
    <div className="ch-think" role="status" aria-live="polite" aria-label={`${resumed ? "Still working on this answer" : "Thinking"}, ${statusSecs} seconds`} data-testid="thinking" data-word-index={idx} data-resumed={resumed || undefined}>
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" style={{ flexShrink: 0 }}>
        <circle cx="12" cy="12" r="9" fill="none" stroke="rgba(59,232,255,0.18)" strokeWidth="2.5" />
        <g className="ch-ring">
          <path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke="#3BE8FF" strokeWidth="2.5" strokeLinecap="round" />
        </g>
      </svg>
      {resumed ? (
        <span aria-hidden="true" className="ch-word" data-testid="spinner-word">
          Still working on this answer…
        </span>
      ) : (
        <span aria-hidden="true" className={`ch-word${reduced ? "" : " in"}`} key={tick} data-testid="spinner-word">
          {words[idx]}
        </span>
      )}
      <span className="ch-secs" aria-hidden="true" data-testid="thinking-seconds">
        {secs} s
      </span>
    </div>
  );
}
