"use client";

import type { DraftCard } from "@/lib/api";
import { Spinner } from "@/components/home/TeamCard";

/** Prompt W11: the draft team's Home pieces (brief sections 2-4) -- the team card with ONE accent changed (amber), the DRAFT
 *  badge + "NOT IN FPL YET" on every draft surface. Value and money left are at current prices; predicted points are the
 *  LATEST predictions (GET /me/draft). */

export function money(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `£${n.toFixed(1)}m`;
}

export const Arrow = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
export const OutArrow = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M7 17L17 7M9 7h8v8" />
  </svg>
);
export const RebuildIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-3-6.7" />
    <path d="M21 4v5h-5" />
  </svg>
);
export const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
  </svg>
);
export const BuildIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 12h18" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

/** "DRAFT" is real text: a screen reader hears "Draft, not in FPL yet" with the line beside it. */
export function DraftBadge({ small = false }: { small?: boolean }) {
  return (
    <span className={`dr-badge${small ? " sm" : ""}`} data-testid="draft-badge">
      DRAFT
    </span>
  );
}

export function NotInFpl() {
  return <span className="dr-notin">NOT IN FPL YET</span>;
}

export function RuleChips() {
  return (
    <div className="dr-rules" data-testid="draft-rules">
      <span className="dr-rule">£100.0m</span>
      <span className="dr-rule">2 GK · 5 DEF · 5 MID · 3 FWD</span>
      <span className="dr-rule">Max 3 per club</span>
    </div>
  );
}

/** "{formation} · C {captain} · built from our predictions" */
export function summaryLine(d: DraftCard): string {
  return `${d.formation} · C ${d.captain?.short_name ?? "—"} · built from our predictions`;
}

/** The owner's checkpoint-1 line: shown when the draft was built from an older run than the latest; opens the normal Rebuild
 *  confirm; nothing automatic. */
export function NewerLine({ onRebuild }: { onRebuild: () => void }) {
  return (
    <div className="dr-newer" data-testid="draft-newer">
      <span>Newer predictions:</span>
      <button type="button" onClick={onRebuild} data-testid="draft-newer-rebuild">
        rebuild?
      </button>
    </div>
  );
}

function Stats({ d }: { d: DraftCard }) {
  const over = (d.over ?? 0) > 0;
  return (
    <dl className="hm-stats dr-stats" data-testid="draft-stats">
      <div className="hm-stat">
        <dt>PRED. GW{d.predictions_gw ?? d.next_gw ?? "?"}</dt>
        <dd data-testid="draft-pred">{d.predicted_xi_points === null ? "—" : d.predicted_xi_points.toFixed(1)}</dd>
      </div>
      <div className="hm-stat">
        <dt>VALUE</dt>
        <dd data-testid="draft-value">{money(d.value)}</dd>
        <span className="dr-of">of {money(d.budget)}</span>
      </div>
      <div className="hm-stat">
        <dt>{over ? "OVER" : "LEFT"}</dt>
        <dd className={over ? "dr-over" : "dr-left"} data-testid="draft-left">
          {over ? `${money(d.over)} over` : money(d.left)}
        </dd>
      </div>
    </dl>
  );
}

type CardActions = { onChat: () => void; onGuide: () => void; onRebuild: () => void; onDelete: () => void; busy: boolean };

function Actions({ onGuide, onRebuild, onDelete, busy }: Omit<CardActions, "onChat">) {
  return (
    <div className="dr-acts">
      <button type="button" className="dr-link" onClick={onGuide} data-testid="draft-guide">
        Enter it in FPL
        <OutArrow />
      </button>
      <span className="grp">
        <button type="button" className="hm-btn-t" onClick={onRebuild} disabled={busy} data-testid="draft-rebuild">
          <RebuildIcon />
          Rebuild
        </button>
        <button type="button" className="hm-btn-t dr-del" onClick={onDelete} disabled={busy} aria-label="Delete draft" data-testid="draft-delete">
          <TrashIcon />
          Delete
        </button>
      </span>
    </div>
  );
}

function ChatButton({ onChat, busy }: { onChat: () => void; busy: boolean }) {
  return (
    <button type="button" className="dr-btn" onClick={onChat} disabled={busy} data-testid="draft-chat">
      {busy ? (
        <>
          <Spinner /> Opening chat…
        </>
      ) : (
        <>
          Chat about this draft
          <Arrow />
        </>
      )}
    </button>
  );
}

/** The draft card: a card in the 3-column grid (0-2 real teams) or a full-width row under the 3 team cards. */
export function DraftHomeCard({ d, layout, ...a }: { d: DraftCard; layout: "card" | "row" } & CardActions) {
  const label = "Your draft team — not in FPL yet";
  if (layout === "row") {
    return (
      <article className="hm-glass dr-card dr-row" aria-label={label} data-testid="draft-card" data-layout="row" data-version={d.version_id}>
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        <div className="dr-names" style={{ gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <DraftBadge />
            <NotInFpl />
          </div>
          <h3>Your draft team</h3>
          <p data-testid="draft-summary">{summaryLine(d)}</p>
          {d.newer_predictions && <NewerLine onRebuild={a.onRebuild} />}
        </div>
        <Stats d={d} />
        <div className="dr-side">
          <ChatButton onChat={a.onChat} busy={a.busy} />
          <Actions onGuide={a.onGuide} onRebuild={a.onRebuild} onDelete={a.onDelete} busy={a.busy} />
        </div>
      </article>
    );
  }
  return (
    <article className="hm-glass hm-team dr-card" aria-label={label} data-testid="draft-card" data-layout="card" data-version={d.version_id}>
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="dr-top">
        <DraftBadge />
        <NotInFpl />
      </div>
      <div className="dr-names">
        <h3>Your draft team</h3>
        <p data-testid="draft-summary">{summaryLine(d)}</p>
      </div>
      <Stats d={d} />
      {d.newer_predictions && <NewerLine onRebuild={a.onRebuild} />}
      <Actions onGuide={a.onGuide} onRebuild={a.onRebuild} onDelete={a.onDelete} busy={a.busy} />
      <div className="hm-team-cta">
        <ChatButton onChat={a.onChat} busy={a.busy} />
      </div>
    </article>
  );
}

/** The new user's middle card: "No FPL team yet? Build one" -- or, once a draft exists, its mini summary + "Open your draft". */
export function BuildChoice({ d, busy, onBuild, onOpen }: { d: DraftCard | null; busy: boolean; onBuild: () => void; onOpen: () => void }) {
  if (d) {
    return (
      <section className="hm-glass hm-choice dr-card" aria-labelledby="choice-draft" data-testid="choice-draft" data-state="exists">
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        <div className="dr-choice-top">
          <DraftBadge />
          <NotInFpl />
        </div>
        <h2 id="choice-draft">Your draft team</h2>
        <p className="dr-mini" data-testid="draft-mini">
          {d.formation} · C {d.captain?.short_name ?? "—"} · {money(d.value)} of {money(d.budget)} · not in FPL yet.
        </p>
        <div className="hm-team-cta">
          <button type="button" className="dr-btnp" onClick={onOpen} disabled={busy} data-testid="open-draft">
            {busy ? (
              <>
                <Spinner /> Opening chat…
              </>
            ) : (
              <>
                Open your draft
                <Arrow />
              </>
            )}
          </button>
        </div>
      </section>
    );
  }
  return (
    <section className="hm-glass hm-choice dr-card" aria-labelledby="choice-draft" data-testid="choice-draft" data-state="build">
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="dr-choice-top">
        <span className="dr-cicon" aria-hidden="true">
          <BuildIcon />
        </span>
        <span className="dr-few">TAKES A FEW SECONDS</span>
      </div>
      <h2 id="choice-draft">No FPL team yet? Build one</h2>
      <p>We pick the best 15 from our predictions — within FPL’s rules — then you tweak it in chat.</p>
      <RuleChips />
      <div className="hm-team-cta">
        <button type="button" className="dr-btnp" onClick={onBuild} disabled={busy} data-testid="build-draft">
          Build my draft team
          <Arrow />
        </button>
      </div>
    </section>
  );
}

/** Returning users without a draft: the small dashed amber pill beside "n of 3 teams" (it stays at 3 of 3: a draft never uses
 *  a slot; it hides once a draft exists). */
export function BuildPill({ onBuild, busy }: { onBuild: () => void; busy: boolean }) {
  return (
    <button type="button" className="dr-pill" onClick={onBuild} disabled={busy} data-testid="build-pill">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <path d="M12 5v14M5 12h14" />
      </svg>
      Build a draft team
    </button>
  );
}

/** With 2 real teams + a draft, Add team shrinks to the slim dashed row under the grid. */
export function SlimAddRow({ slotsLeft, onOpen }: { slotsLeft: number; onOpen: () => void }) {
  return (
    <button type="button" className="hm-slimadd" onClick={onOpen} data-testid="add-team-slim">
      <span className="plus" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </span>
      <span className="txt">
        <b>Add team</b>
        <span>Paste your FPL team ID or link</span>
      </span>
      <span className="slots">
        {slotsLeft} {slotsLeft === 1 ? "SLOT" : "SLOTS"} LEFT
      </span>
    </button>
  );
}
