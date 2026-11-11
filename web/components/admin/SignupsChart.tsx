"use client";

import { useState } from "react";
import { fmtDay, fmtDayYear } from "./format";

/** Sign-ups per UTC day, last 30 days (Prompt W6): plain CSS bars, one focusable button per day -- hover or focus shows
 *  the date and the count in the tip above it -- and a visually hidden table of the same numbers for screen readers. */
export function SignupsChart({ days }: { days: { day: string; n: number }[] }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...days.map((d) => d.n));
  const total = days.reduce((a, d) => a + d.n, 0);
  const cur = active === null ? null : days[active];
  return (
    <div className="ad-chart" data-testid="signups-chart" data-days={days.length} data-total={total}>
      {total === 0 && (
        <p className="ad-empty" data-testid="signups-empty">
          No sign-ups yet.
        </p>
      )}
      <div className="ad-chart-area" onMouseLeave={() => setActive(null)}>
        <div className={`ad-tip${cur ? " on" : ""}`} aria-hidden="true" style={{ left: `${active === null ? 0 : ((active + 0.5) / days.length) * 100}%` }} data-testid="chart-tip">
          {cur ? `${fmtDayYear(cur.day)} · ${cur.n} sign-up${cur.n === 1 ? "" : "s"}` : ""}
        </div>
        <div className="ad-bars" role="group" aria-label="Sign-ups per day, last 30 days">
          {days.map((d, i) => (
            <button
              type="button"
              key={d.day}
              className={`ad-bar${active === i ? " on" : ""}`}
              style={{ ["--h" as string]: `${Math.max(2, Math.round((d.n / max) * 100))}%` }}
              aria-label={`${fmtDayYear(d.day)}: ${d.n} sign-up${d.n === 1 ? "" : "s"}`}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              data-day={d.day}
              data-n={d.n}
            >
              <span aria-hidden="true" />
            </button>
          ))}
        </div>
        <div className="ad-axis" aria-hidden="true">
          <span>{days.length ? fmtDay(days[0].day) : ""}</span>
          <span>{days.length ? fmtDay(days[Math.floor(days.length / 2)].day) : ""}</span>
          <span>{days.length ? fmtDay(days[days.length - 1].day) : ""}</span>
        </div>
      </div>
      <table className="ad-sr">
        <caption>Sign-ups per day (UTC), last 30 days</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">Sign-ups</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.day}>
              <td>{fmtDayYear(d.day)}</td>
              <td>{d.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
