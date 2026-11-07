"use client";

import { useEffect, useRef, useState } from "react";
import type { Source } from "@/lib/api";
import { dayLong, dayShort } from "@/lib/time";

const OPEN_EVENT = "fpl-source-open";
const DocIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4h12l4 4v12H4z" />
    <path d="M8 12h8M8 16h5" />
  </svg>
);

/** The chip's label: "{source name} · {d Mon}"; an FPL note reads "FPL injury news". */
function chipName(s: Source): string {
  return s.name === "FPL" ? "FPL injury news" : s.name;
}
function sourceLine(s: Source): string {
  return s.name === "FPL" ? "Official FPL player note" : s.name;
}

/** SOURCES label + chips under an answer; tapping a chip opens the glass pop-up above it (one open at a time across the
 *  page; Esc or a click outside closes it); "Open article ↗" only when there is a link. */
export function SourcesRow({ sources, id }: { sources: Source[]; id: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open === null) return;
    const onOther = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== id) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    const onClick = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(null);
    };
    window.addEventListener(OPEN_EVENT, onOther);
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener(OPEN_EVENT, onOther);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open, id]);
  if (!sources.length) return null;
  const toggle = (i: number) => {
    const next = open === i ? null : i;
    if (next !== null) window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: id }));
    setOpen(next);
  };
  return (
    <div className="ch-src-row" ref={root} data-testid="sources">
      <span className="ch-src-lbl">SOURCES</span>
      {sources.map((s, i) => (
        <div className="ch-src-wrap" key={i}>
          <button type="button" className={`ch-cite${open === i ? " on" : ""}`} onClick={() => toggle(i)} aria-expanded={open === i} aria-controls={`${id}-src-${i}`} data-testid="source-chip">
            <DocIcon />
            {chipName(s)} · {dayShort(s.date)}
          </button>
          {open === i && (
            <div className="ch-src-pop" role="dialog" aria-label="Source details" id={`${id}-src-${i}`} data-testid="source-popup">
              <span className="mono ch-src-k">
                {chipName(s).toUpperCase()} · {dayLong(s.date)}
              </span>
              <b>{s.headline}</b>
              <span className="ch-src-s">{sourceLine(s)}{s.url ? "" : s.name === "FPL" ? " · no article link" : ""}</span>
              {s.url && (
                <a href={s.url} target="_blank" rel="noopener noreferrer" data-testid="source-link">
                  Open article
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M7 17L17 7M9 7h8v8" />
                  </svg>
                </a>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
