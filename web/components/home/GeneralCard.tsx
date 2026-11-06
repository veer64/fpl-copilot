"use client";

import Link from "next/link";
import type { ThreadRow } from "@/lib/api";
import { shortTeamName, timeAgo } from "@/lib/time";
import { Spinner } from "./TeamCard";

const Arrow = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export const BallIcon = ({ size = 24 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7l4 3-1.5 4.5h-5L8 10z" />
  </svg>
);

/** The example questions; the gameweek is the next deadline's. */
export function exampleChips(nextGw: number | null): string[] {
  const gw = nextGw ? `GW${nextGw}` : "this gameweek";
  return ["Who’s in form right now?", `Best captain for ${gw}?`, "Which cheap defenders are worth it?", "Who’s injured this week?"];
}

export function Chips({ nextGw, onChip }: { nextGw: number | null; onChip: (q: string) => void }) {
  return (
    <div className="hm-try">
      <span className="hm-lbl" style={{ color: "#8A9BB0" }}>
        Try asking
      </span>
      <div className="hm-chips" data-testid="chips">
        {exampleChips(nextGw).map((q) => (
          <button type="button" className="hm-chip" key={q} onClick={() => onChip(q)} data-testid="chip">
            {q}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#7FE9FF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M7 17L17 7M9 7h8v8" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}

export function GeneralCard({
  nextGw,
  wide,
  busy,
  onGeneral,
  onChip,
}: {
  nextGw: number | null;
  wide: boolean;
  busy: boolean;
  onGeneral: () => void;
  onChip: (q: string) => void;
}) {
  return (
    <section className={`hm-glass hm-gen${wide ? " wide" : ""}`} aria-labelledby="gen-title" data-testid="general-card">
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="hm-gen-head">
        <span className="hm-gen-icon" aria-hidden="true">
          <BallIcon />
        </span>
        <div>
          <h2 id="gen-title">Ask without a team</h2>
          <p>Player form, who to buy, captaincy, fixtures — no team needed.</p>
        </div>
      </div>
      <Chips nextGw={nextGw} onChip={onChip} />
      <div className="hm-gen-cta">
        <button type="button" className="hm-btn-o" onClick={onGeneral} disabled={busy} data-testid="start-general">
          {busy ? (
            <>
              <Spinner /> Opening chat…
            </>
          ) : (
            <>
              Start a general chat
              <Arrow />
            </>
          )}
        </button>
      </div>
    </section>
  );
}

export function RecentChats({ threads, now }: { threads: ThreadRow[]; now: Date | null }) {
  const rows = threads.slice(0, 5);
  return (
    <aside className="hm-glass hm-recent" aria-labelledby="recent-title" data-testid="recent-chats">
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="hm-recent-head">
        <h2 id="recent-title" className="hm-lbl">
          Recent chats
        </h2>
        <span className="mono" style={{ fontSize: 11, color: "#8A9BB0" }}>
          LAST {rows.length}
        </span>
      </div>
      {rows.map((t) => (
        <Link href={`/chat/${t.thread_id}`} className="hm-row" key={t.thread_id} data-testid="recent-row" data-thread-id={t.thread_id}>
          <span className="hm-row-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
            </svg>
          </span>
          <span className="hm-row-body">
            <span className="hm-row-title">{t.title ?? "New chat"}</span>
            <span className="hm-row-meta">
              <span className={`hm-tag ${t.fpl_team_id ? "hm-tag-team" : "hm-tag-gen"}`}>{t.fpl_team_id ? shortTeamName(t.team_label) : "GENERAL"}</span>
              <span className="hm-row-ago">{now ? timeAgo(t.last_active, now) : ""}</span>
            </span>
          </span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5E7184" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </Link>
      ))}
    </aside>
  );
}
