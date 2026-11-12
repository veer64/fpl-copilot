"use client";

import { toast } from "sonner";
import type { TeamCard as Card } from "@/lib/api";
import { fmtInt, usedAgoTag } from "@/lib/time";

const Arrow = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export const Spinner = () => <span className="hm-spin" aria-hidden="true" />;

export function teamName(t: Card): string {
  return (t.label ?? t.entry_name ?? `Team ${t.fpl_team_id}`).trim();
}

export function TeamCard({
  team,
  lastUsed,
  now,
  isNew,
  busy,
  refreshFailed,
  onAsk,
  onRefresh,
  onRemove,
}: {
  team: Card;
  lastUsed: boolean;
  now: Date | null;
  isNew: boolean;
  busy: "ask" | "refresh" | null;
  refreshFailed: boolean;
  onAsk: () => void;
  onRefresh: () => void;
  /** Prompt W5: the trash button next to Refresh -> the Remove team confirm */
  onRemove?: () => void;
}) {
  const name = teamName(team);
  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(String(team.fpl_team_id));
      toast("Team ID copied");
    } catch {
      toast.error("Couldn’t copy the ID");
    }
  };
  const gwLabel = team.last_gw ? `GW${team.last_gw}` : "GW";
  return (
    <article
      className={`hm-glass hm-team${lastUsed ? " last" : ""}`}
      aria-label={name}
      data-testid="team-card"
      data-team-id={team.fpl_team_id}
      data-last-used={lastUsed}
      data-active={team.is_active}
      data-new={isNew}
    >
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="hm-team-top">
        {lastUsed ? (
          <span className="hm-tag hm-tag-last">LAST USED</span>
        ) : (
          <span className="hm-tag hm-tag-ago">{now ? usedAgoTag(team.last_used_at, now) : ""}</span>
        )}
        <button type="button" className="hm-idchip" aria-label={`Copy team ID ${team.fpl_team_id}`} onClick={copyId} data-testid="copy-id">
          <span>ID</span>
          {team.fpl_team_id}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15V6a2 2 0 0 1 2-2h9" />
          </svg>
        </button>
      </div>
      <div className="hm-team-names">
        <h3 title={name}>{name}</h3>
        <p>{team.manager_name ?? (team.entry_name && team.entry_name !== name ? team.entry_name : " ")}</p>
      </div>
      <dl className="hm-stats">
        <div className="hm-stat">
          <dt>TOTAL</dt>
          <dd data-testid="stat-total">{fmtInt(team.total_points)}</dd>
        </div>
        <div className="hm-stat">
          <dt>RANK</dt>
          <dd data-testid="stat-rank">{fmtInt(team.overall_rank)}</dd>
        </div>
        <div className="hm-stat">
          <dt>{gwLabel}</dt>
          <dd data-testid="stat-gw">{fmtInt(team.last_gw_points)}</dd>
        </div>
      </dl>
      <div className="hm-fresh">
        {refreshFailed ? (
          <span className="hm-fresh-line failed" role="status" data-testid="freshness">
            <i aria-hidden="true" />
            Couldn’t refresh — showing data from GW{team.updated_after_gw ?? "?"}
          </span>
        ) : (
          <span className="hm-fresh-line" data-testid="freshness" data-updated-after-gw={team.updated_after_gw ?? ""} data-summary-updated-at={team.summary_updated_at ?? ""}>
            <i aria-hidden="true" />
            {team.updated_after_gw ? `Updated after GW${team.updated_after_gw}` : "Not updated yet"}
          </span>
        )}
        <button type="button" className="hm-btn-t" aria-label={`Refresh ${name}`} onClick={onRefresh} disabled={busy !== null} data-testid="refresh">
          {busy === "refresh" ? (
            <Spinner />
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 12a9 9 0 1 1-3-6.7" />
              <path d="M21 4v5h-5" />
            </svg>
          )}
          Refresh
        </button>
        {onRemove && (
          <button type="button" className="hm-btn-t hm-btn-trash" aria-label={`Remove ${name}`} onClick={onRemove} disabled={busy !== null} data-testid="remove-team">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
            </svg>
          </button>
        )}
      </div>
      <div className="hm-team-cta">
        <button type="button" className={lastUsed ? "hm-btn-p" : "hm-btn-s"} onClick={onAsk} disabled={busy !== null} data-testid="ask-team">
          {busy === "ask" ? (
            <>
              <Spinner /> Opening chat…
            </>
          ) : (
            <>
              Ask about this team
              <Arrow />
            </>
          )}
        </button>
      </div>
    </article>
  );
}

/** Prompt W7b (F10): at the limit the Add card's place says so (the Home brief: "3 of 3 teams"). */
export function TeamsFull({ max }: { max: number }) {
  return (
    <div className="hm-add hm-full" role="note" data-testid="teams-full">
      <span className="hm-add-title">
        {max} of {max} teams
      </span>
      <span className="hm-add-sub">Remove a team to add another.</span>
    </div>
  );
}

export function AddTeamCard({ slotsLeft, onOpen }: { slotsLeft: number; onOpen: () => void }) {
  return (
    <button type="button" className="hm-add" onClick={onOpen} data-testid="add-team-card">
      <span className="hm-add-plus" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </span>
      <span className="hm-add-text">
        <span className="hm-add-title">Add team</span>
        <span className="hm-add-sub">
          Paste your FPL team ID{" "}
          <br />
          or the link to your team
        </span>
      </span>
      <span className="hm-add-slots">
        {slotsLeft} {slotsLeft === 1 ? "SLOT" : "SLOTS"} LEFT
      </span>
    </button>
  );
}
