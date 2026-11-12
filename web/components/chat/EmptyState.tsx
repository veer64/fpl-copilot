"use client";

import type { DraftCard, Player, TeamCardData } from "@/lib/api";
import { draftChips } from "@/lib/draft-chips";

const Arrow = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
const LogoMark = ({ size }: { size: number }) => (
  <svg width={size} height={size} viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
    <path d="M14 2 L25 8.5 V19.5 L14 26 L3 19.5 V8.5 Z" />
    <path d="M9 17 L14 11 L19 17" />
  </svg>
);

/** The squad's most doubtful player: the lowest chance of playing among the flagged, the XI before the bench on ties. */
export function mostDoubtful(players: Player[]): Player | null {
  const flagged = players.filter((p) => p.flag);
  if (!flagged.length) return null;
  const chance = (p: Player) => (p.flag?.chance === null || p.flag?.chance === undefined ? 100 : p.flag.chance);
  return [...flagged].sort((a, b) => chance(a) - chance(b) || (a.slot ?? 99) - (b.slot ?? 99))[0];
}

export function teamChips(card: TeamCardData | null, nextGw: number | null): string[] {
  const gw = nextGw ? `GW${nextGw}` : "this gameweek";
  const doubtful = card ? mostDoubtful(card.players) : null;
  return [
    `Who should I captain for ${gw}?`,
    `What’s my best transfer for ${gw}?`,
    doubtful ? `Is ${doubtful.short_name} fit to play?` : "Who’s the weakest player in my team?",
    "Which of my players have the best fixtures?",
  ];
}

export function generalChips(nextGw: number | null): string[] {
  const gw = nextGw ? `GW${nextGw}` : "this gameweek";
  return ["Who’s in form right now?", `Best captain picks for ${gw}?`, "Best picks of the week?", "Who’s injured this week?"];
}

/** The empty chat: Team mode (label, h2, sub, four chips -- the injury chip names the squad's most doubtful player) or General
 *  mode (label, h1 with the first name, sub, four chips). Chips fill the chat box and focus it; they never send. */
export function EmptyState({
  mode,
  teamName,
  nextGw,
  card,
  firstName,
  onChip,
  draft,
  onGuide,
}: {
  mode: "team" | "general" | "draft";
  teamName: string | null;
  nextGw: number | null;
  card: TeamCardData | null;
  firstName: string | null;
  onChip: (q: string) => void;
  /** Prompt W11: a new draft chat's empty state -- the draft's own chips (O3), never the Team / General ones */
  draft?: DraftCard | null;
  onGuide?: () => void;
}) {
  if (mode === "draft") return <DraftEmpty d={draft ?? null} onChip={onChip} onGuide={onGuide} />;
  const chips = mode === "team" ? teamChips(card, nextGw) : generalChips(nextGw);
  const name = teamName ?? "your team";
  return (
    <div className={`ch-empty${mode === "general" ? " general" : ""}`} data-testid={`empty-${mode}`} data-ready={mode === "general" || card !== null}>
      <div className="ch-empty-head">
        <span className="ch-empty-icon" aria-hidden="true">
          <LogoMark size={mode === "general" ? 26 : 24} />
        </span>
        <span className="ch-lbl" data-testid="empty-label">
          {mode === "team" ? `New chat · ${name}` : "General chat"}
        </span>
        {mode === "team" ? (
          <h2 data-testid="empty-title">Ask anything about {name}.</h2>
        ) : (
          <h1 data-testid="empty-title">What do you want to know, {firstName ?? "manager"}?</h1>
        )}
        <p data-testid="empty-sub">
          {mode === "team"
            ? `Answers use your squad as of the GW${card?.squad_as_of_gw ?? (nextGw ? nextGw - 1 : "?")} deadline.`
            : "Best picks for the week, captains, who to buy — ask about any player or club."}
        </p>
      </div>
      <div role="list" aria-label="Suggested questions" className="ch-chips">
        {chips.map((q) => (
          <button type="button" role="listitem" className="ch-chip" key={q} onClick={() => onChip(q)} data-testid="empty-chip">
            <span>{q}</span>
            <Arrow />
          </button>
        ))}
      </div>
    </div>
  );
}

/** Prompt W11: a new draft chat (sidebar "New chat" in draft mode): the draft's chips (O3); the guide chip opens the guide,
 *  the others fill the chat box as every empty state's chips do. */
function DraftEmpty({ d, onChip, onGuide }: { d: DraftCard | null; onChip: (q: string) => void; onGuide?: () => void }) {
  const chips = draftChips({ captain: d?.captain?.short_name ?? null, left: d?.left ?? null, over: d?.over ?? null }).slice(0, 4);
  return (
    <div className="ch-empty draft" data-testid="empty-draft" data-ready={d !== null}>
      <div className="ch-empty-head">
        <span className="ch-empty-icon" aria-hidden="true" style={{ color: "#FFC23D" }}>
          <LogoMark size={24} />
        </span>
        <span className="ch-lbl" data-testid="empty-label">
          New chat · your draft team
        </span>
        <h2 data-testid="empty-title">Ask anything about your draft.</h2>
        <p data-testid="empty-sub">Changes are free — the only limits are £100.0m and FPL’s squad rules.</p>
      </div>
      <div role="list" aria-label="Suggested questions" className="ch-chips">
        {chips.map((c) => (
          <button type="button" role="listitem" className="ch-chip" key={c.text} onClick={() => (c.action === "guide" ? onGuide?.() : onChip(c.text))} data-testid="empty-chip">
            <span>{c.text}</span>
            <Arrow />
          </button>
        ))}
      </div>
    </div>
  );
}
