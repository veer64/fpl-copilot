"use client";

import { useEffect, useMemo, useRef, useState } from "react";

/** Prompt W10 (2026-11-12): the finished answer "writes itself out" on the client -- the server does not stream. Only an
 *  answer that just arrived in this tab is revealed; history, a reopened chat and prefers-reduced-motion show at once.
 *
 *  Pace: REVEAL_CPS characters a second, but never longer than REVEAL_MAX_MS (a long answer goes faster), one re-render
 *  every REVEAL_TICK_MS at most (20 a second). The prefix shown is always cut at a SAFE point of the markdown, so no frame
 *  shows a raw marker: paragraphs grow word by word but never inside an unclosed **bold**, *italic*, `code`, ~~strike~~ or
 *  [link](url); a heading, a list item, a quote or a rule appears whole; a table appears once its header and separator
 *  rows are complete, then row by row; a fenced code block appears whole. */

export const REVEAL_CPS = 300;
export const REVEAL_MAX_MS = 4000;
export const REVEAL_TICK_MS = 50;

export function revealDurationMs(chars: number): number {
  return Math.min((chars / REVEAL_CPS) * 1000, REVEAL_MAX_MS);
}

const FENCE = /^\s{0,3}(```|~~~)/;
const TABLE_ROW = /^\s*\|/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const WHOLE_LINE = /^\s*(#{1,6}\s|>|([-*+]|\d{1,3}[.)])\s|(-{3,}|\*{3,}|_{3,})\s*$)/;

/** Offsets inside one paragraph line where the prefix closes every inline marker it opened (cuts at word ends). */
function wordCuts(line: string): number[] {
  const cuts: number[] = [];
  let bold = false;
  let italic = false;
  let strike = false;
  let code = false;
  let link = 0; // 0 none, 1 inside [text], 2 inside (url)
  for (let k = 0; k < line.length; k++) {
    const c = line[k];
    if (c === "`") {
      code = !code;
      continue;
    }
    if (code) continue;
    if (c === "\\") {
      k++; // an escaped character is literal
      continue;
    }
    if (c === "*" && line[k + 1] === "*") {
      bold = !bold;
      k++;
    } else if (c === "*") {
      italic = !italic;
    } else if (c === "~" && line[k + 1] === "~") {
      strike = !strike;
      k++;
    } else if (c === "[" && link === 0) {
      link = 1;
    } else if (c === "]" && link === 1) {
      link = line[k + 1] === "(" ? 2 : 0;
      if (link === 2) k++;
    } else if (c === ")" && link === 2) {
      link = 0;
    }
    const boundary = /\s/.test(line[k + 1] ?? " ") && !/\s/.test(line[k]);
    if (boundary && !bold && !italic && !strike && !code && link === 0) cuts.push(k + 1);
  }
  return cuts;
}

/** Every safe prefix length of `text`, increasing; the last one is text.length. */
export function revealCuts(text: string): number[] {
  const lines: { start: number; end: number; next: number }[] = [];
  let at = 0;
  while (at <= text.length) {
    const nl = text.indexOf("\n", at);
    const end = nl === -1 ? text.length : nl;
    lines.push({ start: at, end, next: nl === -1 ? text.length : nl + 1 });
    if (nl === -1) break;
    at = nl + 1;
  }
  const cuts: number[] = [];
  const push = (n: number) => {
    if (n > 0 && (cuts.length === 0 || n > cuts[cuts.length - 1])) cuts.push(n);
  };
  const line = (i: number) => text.slice(lines[i].start, lines[i].end);
  for (let i = 0; i < lines.length; ) {
    const s = line(i);
    if (FENCE.test(s)) {
      let j = i + 1;
      while (j < lines.length && !FENCE.test(line(j))) j++;
      push(j < lines.length ? lines[j].next : text.length);
      i = j + 1;
      continue;
    }
    if (TABLE_ROW.test(s) && i + 1 < lines.length && TABLE_SEP.test(line(i + 1))) {
      push(lines[i + 1].next); // the header appears with its separator, never alone
      i += 2;
      while (i < lines.length && TABLE_ROW.test(line(i))) {
        push(lines[i].next); // then row by row
        i++;
      }
      continue;
    }
    if (!s.trim() || WHOLE_LINE.test(s) || TABLE_ROW.test(s)) {
      push(lines[i].next);
      i++;
      continue;
    }
    for (const c of wordCuts(s)) push(lines[i].start + c);
    push(lines[i].next);
    i++;
  }
  push(text.length);
  return cuts;
}

/** The largest cut <= chars (binary search); 0 when none fits yet. */
function cutAt(cuts: number[], chars: number): number {
  let lo = 0;
  let hi = cuts.length - 1;
  let best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (cuts[mid] <= chars) {
      best = cuts[mid];
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return best;
}

/** The revealed prefix of `text`: everything at once unless `animate`; when `animate` turns false mid-way (a new message
 *  was sent, the tab was hidden) the whole text shows at once. The interval stops when done and on unmount, and a page
 *  hidden by the router (Next keeps it mounted; its effects are cleaned up) finishes its reveal rather than resuming it.
 *  (In development, React's strict mode replays effects once on mount, so the reveal shows at once there.) */
export function useReveal(text: string, animate: boolean): { shown: string; done: boolean } {
  const cuts = useMemo(() => (animate ? revealCuts(text) : []), [text, animate]);
  const [chars, setChars] = useState(animate ? 0 : text.length);
  const started = useRef<number | null>(null);
  const finished = useRef(false); // once hidden or unmounted mid-way, the answer stays whole (never resumes typing)
  useEffect(() => {
    if (!animate || finished.current) return;
    const total = text.length;
    const duration = revealDurationMs(total);
    started.current ??= performance.now();
    const t0 = started.current;
    let last = -1;
    const tick = () => {
      const elapsed = performance.now() - t0;
      const next = elapsed >= duration ? total : cutAt(cuts, (total * elapsed) / duration);
      if (next !== last) {
        last = next;
        setChars(next);
      }
      if (next >= total) window.clearInterval(timer);
    };
    const timer = window.setInterval(tick, REVEAL_TICK_MS);
    tick();
    return () => {
      window.clearInterval(timer);
      finished.current = true; // hidden by the router (the page stays mounted) or leaving: finish, never restart
      setChars(total);
    };
  }, [animate, text, cuts]);
  const done = !animate || chars >= text.length;
  return { shown: done ? text : text.slice(0, chars), done };
}
