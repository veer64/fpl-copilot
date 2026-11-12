"use client";

import { useEffect, useMemo, useState } from "react";
import type { ApiError, DraftCard, DraftResult, Player, SquadPreview } from "@/lib/api";
import { stampUtc } from "@/lib/time";
import type { Resource } from "@/components/home/useResource";
import { DraftBadge, NewerLine, RebuildIcon, money } from "@/components/draft/DraftParts";
import { Bench, Pitch, pitchSlots } from "./Pitch";
import { PlayerSheet } from "./MobileTeam";
import { PreviewLine } from "./TeamCardPanel";

/** Prompt W11 (brief section 6): the chat's team card in DRAFT mode -- the team card exactly, with the amber accent: the
 *  amber pitch icon, the DRAFT badge, "Your draft team", the meta line "4-4-2 · £99.6m OF £100.0M · £0.4m LEFT" (no free
 *  transfers or bank: changes are free; "£0.2m OVER" in coral after price rises), a Rebuild icon button instead of Refresh,
 *  Hide/Show, the same pitch / bench / tokens / hover card, NO FPL chips row, and the footer "BUILT FROM PREDICTIONS UPDATED
 *  {date}". Predicted points on the tokens are the LATEST predictions (the card's own pool). */

const AmberPitch = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FFC23D" strokeWidth="1.8" aria-hidden="true" style={{ flexShrink: 0 }}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 12h18" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export function DraftMeta({ d }: { d: DraftCard }) {
  const over = (d.over ?? 0) > 0;
  return (
    <>
      {d.formation} · {money(d.value)} OF {money(d.budget).toUpperCase()} ·{" "}
      {over ? <b className="over">{money(d.over)} OVER</b> : <b>{money(d.left)} LEFT</b>}
    </>
  );
}

function builtLine(d: DraftCard): string {
  const at = d.built_from_predictions_at ?? d.built_at;
  return at ? `BUILT FROM PREDICTIONS UPDATED ${stampUtc(at).toUpperCase()}` : "BUILT FROM OUR PREDICTIONS";
}

function Problem({ onRetry, gone }: { onRetry: () => void; gone: boolean }) {
  return (
    <section className="ch-card ch-card-err dr-card" aria-label="Your draft team" data-testid="card-error">
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <b>{gone ? "Your draft was deleted" : "Couldn’t load your draft"}</b>
      <span>{gone ? "Build a new one from Home." : "You can keep chatting meanwhile."}</span>
      {!gone && (
        <button type="button" className="ch-btn-s" onClick={onRetry} data-testid="card-retry">
          Retry
        </button>
      )}
    </section>
  );
}

export function DraftPanel({
  draft,
  preview,
  open,
  onToggle,
  onRebuild,
  onRetry,
  rebuilding,
}: {
  draft: Resource<DraftResult>;
  preview: SquadPreview | null;
  open: boolean;
  onToggle: () => void;
  onRebuild: () => void;
  onRetry: () => void;
  rebuilding: boolean;
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
  const d = draft.status === "ready" ? draft.data.draft : null;
  const slots = useMemo(() => (d ? pitchSlots(d.players, preview) : null), [d, preview]);
  const pick = (p: Player) => setPinned((cur) => (cur === p.id ? null : p.id));
  if (draft.status === "loading") return <section className="ch-card dr-card" aria-label="Loading your draft" aria-busy="true" data-testid="card-skeleton"><span className="ch-sk" style={{ height: 380, borderRadius: 12 }} /></section>;
  if (draft.status === "error" || !d || !slots) return <Problem onRetry={onRetry} gone={draft.status === "ready" && !d} />;
  return (
    <section className="ch-card dr-card" aria-label="Your draft team — not in FPL yet" data-testid="team-card" data-draft="true" data-version={d.version_id}>
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="ch-card-head">
        <AmberPitch />
        <div className="ch-card-names">
          <span className="ch-card-name" data-testid="card-name" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <DraftBadge small />
            Your draft team
          </span>
          <span className="ch-card-line" data-testid="card-line">
            <DraftMeta d={d} />
          </span>
        </div>
        <button type="button" className="ch-ib-s" aria-label="Rebuild draft" title="Rebuild draft" onClick={onRebuild} disabled={rebuilding} data-testid="card-rebuild">
          {rebuilding ? <span className="hm-spin" aria-hidden="true" style={{ width: 14, height: 14 }} /> : <RebuildIcon />}
        </button>
        <button type="button" className="ch-ib-s" aria-expanded={open} aria-label={open ? "Hide team" : "Show team"} title={open ? "Hide team" : "Show team"} onClick={onToggle} data-testid="card-toggle">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: open ? undefined : "rotate(180deg)" }}>
            <path d="M6 15l6-6 6 6" />
          </svg>
        </button>
      </div>
      {open && (
        <>
          {d.newer_predictions && <NewerLine onRebuild={onRebuild} />}
          {preview && <PreviewLine preview={preview} />}
          <div className="ch-pitch-area">
            <Pitch slots={slots} pinnedId={pinned} onPick={pick} nextGw={d.next_gw} phone={false} />
            <Bench slots={slots} pinnedId={pinned} onPick={pick} nextGw={d.next_gw} phone={false} />
          </div>
          <div className="ch-card-foot" data-testid="card-footer">
            <span>NOT IN FPL YET · CHANGES ARE FREE · HOVER A PLAYER</span>
            <span>{builtLine(d)}</span>
          </div>
        </>
      )}
    </section>
  );
}

/** The phone: "DRAFT · 4-4-2 · C HAALAND" with the amber badge, and the panel it slides open (the meta line + Rebuild, the
 *  pitch, the bench; no chips row). */
export function MobileDraft({
  draft,
  preview,
  open,
  onToggle,
  onRebuild,
  onRetry,
  rebuilding,
}: {
  draft: Resource<DraftResult>;
  preview: SquadPreview | null;
  open: boolean;
  onToggle: () => void;
  onRebuild: () => void;
  onRetry: () => void;
  rebuilding: boolean;
}) {
  const [sheet, setSheet] = useState<Player | null>(null);
  const d = draft.status === "ready" ? draft.data.draft : null;
  const slots = useMemo(() => (d ? pitchSlots(d.players, preview) : null), [d, preview]);
  const captain = d?.players.find((p) => p.role === "C");
  const err = draft.status === "error" ? (draft.error as ApiError) : null;
  return (
    <>
      <button type="button" className="ch-teambar dr-card" onClick={onToggle} aria-expanded={open} aria-controls="m-pitch" data-testid="team-bar" data-draft="true">
        <AmberPitch />
        <span className="ch-teambar-names">
          <span className="ch-teambar-name" data-testid="team-bar-name" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <DraftBadge small />
            Your draft team
          </span>
          <span className="ch-teambar-line" data-testid="team-bar-line">
            {draft.status === "loading" ? "Loading your draft…" : err || !d ? "Couldn’t load your draft" : `DRAFT · ${d.formation} · C ${(captain?.short_name ?? "—").toUpperCase()}`}
          </span>
        </span>
        {preview && (
          <span className="ch-changes-pill" data-testid="changes-pill">
            {preview.changes.length} {preview.changes.length === 1 ? "CHANGE" : "CHANGES"}
          </span>
        )}
        <svg className="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div id="m-pitch" className="ch-panel" data-testid="pitch-panel">
          {draft.status === "loading" && <span className="ch-sk" style={{ height: 250, borderRadius: 12 }} aria-label="Loading your draft" />}
          {(draft.status === "error" || (draft.status === "ready" && !slots)) && (
            <div className="ch-card-err" style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center", textAlign: "center", padding: "12px 0" }} data-testid="card-error">
              <b>{draft.status === "ready" && !d ? "Your draft was deleted" : "Couldn’t load your draft"}</b>
              {draft.status === "error" && (
                <button type="button" className="ch-btn-s" onClick={onRetry} data-testid="card-retry">
                  Retry
                </button>
              )}
            </div>
          )}
          {d && slots && (
            <>
              <div className="ch-panel-top">
                <span className="line" data-testid="panel-line">
                  <DraftMeta d={d} />
                </span>
                <button type="button" className="ch-panel-refresh" aria-label="Rebuild draft" onClick={onRebuild} disabled={rebuilding} data-testid="card-rebuild">
                  <RebuildIcon size={12} />
                  Rebuild
                </button>
              </div>
              {d.newer_predictions && <NewerLine onRebuild={onRebuild} />}
              <Pitch slots={slots} pinnedId={null} onPick={setSheet} nextGw={d.next_gw} phone />
              <Bench slots={slots} pinnedId={null} onPick={setSheet} nextGw={d.next_gw} phone />
              <span className="ch-card-foot" style={{ display: "block" }}>
                <span>{builtLine(d)}</span>
              </span>
            </>
          )}
        </div>
      )}
      {sheet && d && <PlayerSheet p={sheet} nextGw={d.next_gw} onClose={() => setSheet(null)} />}
    </>
  );
}
