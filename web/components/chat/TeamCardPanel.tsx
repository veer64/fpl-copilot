"use client";

import { useEffect, useMemo, useState } from "react";
import type { ApiError, Player, SquadPreview, TeamCardData } from "@/lib/api";
import { stampUtc } from "@/lib/time";
import type { Resource } from "@/components/home/useResource";
import { Bench, Pitch, pitchSlots } from "./Pitch";
import { price } from "./PreviewCard";

export type RefreshState = "idle" | "busy" | "failed" | "limited";

const PitchIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5BE3A4" strokeWidth="1.8" aria-hidden="true" style={{ flexShrink: 0 }}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 12h18" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);
const RefreshIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-3-6.7" />
    <path d="M21 4v5h-5" />
  </svg>
);

export function headerLine(card: TeamCardData): string {
  return `${card.formation} · BANK ${price(card.bank)} · ${card.free_transfers ?? "?"} FT · ${card.team_value === null ? "—" : price(card.team_value)}`;
}

export function previewLine(preview: SquadPreview): { out: string; in: string; word: string | null } | { count: number } {
  if (preview.changes.length === 1) {
    const ch = preview.changes[0];
    return { out: ch.out.short_name, in: ch.in.short_name, word: ch.type === "transfer" ? null : ch.type === "captain" ? "CAPTAIN" : ch.type === "vice_captain" ? "VICE" : "BENCH" };
  }
  return { count: preview.changes.length };
}

export function ChipsRow({ card, phone }: { card: TeamCardData; phone: boolean }) {
  const chips = card.chips;
  if (!chips) {
    return phone ? null : (
      <div className="ch-chips-blk" data-testid="chips-row">
        <div className="ch-chips-head">
          <span className="lbl">CHIPS</span>
          <span className="n">unavailable while FPL is unreachable</span>
        </div>
      </div>
    );
  }
  const boxes = chips.items.map((c) => {
    const status = c.used_gw ? `USED GW${c.used_gw}` : "READY";
    return (
      <span className={`ch-chp ${c.used_gw ? "used" : "ok"}`} role="img" aria-label={`${c.name}: ${status}`} title={`${c.name} — ${status}`} key={c.code} data-testid="chip-box" data-code={c.code} data-used={!!c.used_gw}>
        <b>{c.code}</b>
        <i>{status}</i>
      </span>
    );
  });
  if (phone) {
    return (
      <div className="ch-panel-chips" data-testid="chips-row">
        <span className="lbl">CHIPS</span>
        <span className="n">
          <b>{chips.left} left</b> · {chips.used} used
        </span>
        <span className="ch-grow" />
        {boxes}
      </div>
    );
  }
  return (
    <div className="ch-chips-blk" data-testid="chips-row">
      <div className="ch-chips-head">
        <span className="lbl">
          CHIPS · GW{chips.half.from}–{chips.half.to}
        </span>
        <span className="n">
          <b>{chips.left} left</b> · {chips.used} used
        </span>
      </div>
      <div className="ch-chg">{boxes}</div>
    </div>
  );
}

export function PreviewLine({ preview }: { preview: SquadPreview }) {
  const line = previewLine(preview);
  return (
    <div className="ch-pv-line" data-testid="card-preview-line">
      <span className="k">PREVIEW</span>
      {"count" in line ? (
        <span>{line.count} changes</span>
      ) : (
        <>
          {line.word && <span className="k">{line.word}</span>}
          <span className="o">{line.out}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
          <span className="i">{line.in}</span>
        </>
      )}
    </div>
  );
}

export function FplNotes({ card, refresh }: { card: TeamCardData | null; refresh: RefreshState }) {
  return (
    <>
      {card && !card.fpl_live && (
        <div className="ch-note" role="status" data-testid="note-stale">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v5M12 16h.01" />
          </svg>
          Live details may be out of date.
        </div>
      )}
      {(refresh === "failed" || refresh === "limited") && (
        <div className="ch-note" role="status" data-testid="note-refresh">
          <RefreshIcon />
          {refresh === "limited" ? "Refresh limit reached (5 a minute) — showing your saved team." : "FPL isn’t responding — showing your saved team."}
        </div>
      )}
    </>
  );
}

function CardSkeleton() {
  return (
    <section className="ch-card" aria-label="Loading team" aria-busy="true" data-testid="card-skeleton">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="ch-sk" style={{ width: 18, height: 18, borderRadius: 5 }} />
        <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", gap: 5 }}>
          <span className="ch-sk" style={{ height: 11, width: "70%" }} />
          <span className="ch-sk" style={{ height: 8, width: "90%" }} />
        </div>
      </div>
      <span className="ch-sk" style={{ height: 330, borderRadius: 12 }} />
      <span className="ch-sk" style={{ height: 70, borderRadius: 10 }} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 }}>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className="ch-sk" style={{ height: 34 }} />
        ))}
      </div>
    </section>
  );
}

/** The desktop team card (top-right): header + Refresh + Hide/Show, the PREVIEW line while pending, the pitch, the bench,
 *  the chips row, the freshness footer, and the three problem states (chat-states 07). */
export function TeamCardPanel({
  card,
  preview,
  refresh,
  onRefresh,
  onRetry,
  open,
  onToggle,
  teamName,
}: {
  card: Resource<TeamCardData>;
  preview: SquadPreview | null;
  refresh: RefreshState;
  onRefresh: () => void;
  onRetry: () => void;
  open: boolean;
  onToggle: () => void;
  teamName: string | null;
}) {
  const [pinned, setPinned] = useState<number | null>(null);
  useEffect(() => {
    if (pinned === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPinned(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [pinned]);
  const data = card.status === "ready" ? card.data : null;
  const slots = useMemo(() => (data ? pitchSlots(data.players, preview) : null), [data, preview]);
  const pick = (p: Player) => setPinned((cur) => (cur === p.id ? null : p.id));

  if (card.status === "loading") return <CardSkeleton />;
  if (card.status === "error" || !data || !slots) {
    const err = card.status === "error" ? (card.error as ApiError) : null;
    return (
      <section className="ch-card ch-card-err" aria-label="Your team" data-testid="card-error" data-status={err?.status ?? ""}>
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        <span className="ic" aria-hidden="true">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3l9 16H3z" />
            <path d="M12 10v4M12 17h.01" />
          </svg>
        </span>
        <b>Couldn’t load your team</b>
        <span>You can keep chatting meanwhile.</span>
        <button type="button" className="ch-btn-s" onClick={onRetry} data-testid="card-retry">
          <RefreshIcon size={15} />
          Retry
        </button>
      </section>
    );
  }
  return (
    <section className="ch-card" aria-label={`Your team: ${data.team.name}`} data-testid="team-card" data-version={data.version_id} data-live={data.fpl_live}>
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="ch-card-head">
        <PitchIcon />
        <div className="ch-card-names">
          <span className="ch-card-name" data-testid="card-name">
            {teamName ?? data.team.name}
          </span>
          <span className="ch-card-line" data-testid="card-line">
            {headerLine(data)}
          </span>
        </div>
        <button type="button" className="ch-ib-s" aria-label="Refresh team" title="Refresh team" onClick={onRefresh} disabled={refresh === "busy"} data-testid="card-refresh" data-state={refresh}>
          {refresh === "busy" ? <span className="hm-spin" aria-hidden="true" style={{ width: 14, height: 14 }} /> : <RefreshIcon />}
        </button>
        <button type="button" className="ch-ib-s" aria-expanded={open} aria-label={open ? "Hide team" : "Show team"} title={open ? "Hide team" : "Show team"} onClick={onToggle} data-testid="card-toggle">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: open ? undefined : "rotate(180deg)" }}>
            <path d="M6 15l6-6 6 6" />
          </svg>
        </button>
      </div>
      {open && (
        <>
          <FplNotes card={data} refresh={refresh} />
          {preview && <PreviewLine preview={preview} />}
          <div className="ch-pitch-area" onMouseLeave={() => undefined}>
            <Pitch slots={slots} pinnedId={pinned} onPick={pick} nextGw={data.next_gw} phone={false} />
            <Bench slots={slots} pinnedId={pinned} onPick={pick} nextGw={data.next_gw} phone={false} />
          </div>
          <ChipsRow card={data} phone={false} />
          <div className="ch-card-foot" data-testid="card-footer">
            <span>SQUAD AS OF THE GW{data.squad_as_of_gw} DEADLINE · HOVER A PLAYER</span>
            <span>{data.predictions_updated_at ? `PREDICTIONS UPDATED ${stampUtc(data.predictions_updated_at).toUpperCase()}` : "PREDICTIONS UNAVAILABLE · FPL ESTIMATES SHOWN"}</span>
          </div>
        </>
      )}
    </section>
  );
}
