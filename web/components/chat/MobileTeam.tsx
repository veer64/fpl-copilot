"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Player, SquadPreview, TeamCardData, ThreadRow } from "@/lib/api";
import type { Resource } from "@/components/home/useResource";
import { Bench, Pitch, PlayerFacts, pitchSlots } from "./Pitch";
import { price } from "./PreviewCard";
import { ChipsRow, FplNotes, type RefreshState } from "./TeamCardPanel";
import { ThreadList } from "./Sidebar";

/** A modal layer (the phone drawer and the player sheet): Esc closes, the overlay closes, focus is trapped inside and
 *  returned to the opener. */
function Modal({ onClose, label, className, children, testId }: { onClose: () => void; label: string; className: string; children: ReactNode; testId: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(box.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), textarea, input, [tabindex]:not([tabindex="-1"])') ?? []);
    const first = focusables()[0] ?? box.current;
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "Tab") {
        const f = focusables();
        if (!f.length) return;
        const i = f.indexOf(document.activeElement as HTMLElement);
        if (e.shiftKey && (i <= 0 || i === -1)) {
          e.preventDefault();
          f[f.length - 1].focus();
        } else if (!e.shiftKey && i === f.length - 1) {
          e.preventDefault();
          f[0].focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [onClose]);
  return (
    <div className={className} data-testid={testId}>
      <div className="ch-overlay" onClick={onClose} aria-hidden="true" />
      <div role="dialog" aria-modal="true" aria-label={label} ref={box} tabIndex={-1} className={className === "ch-drawer-root" ? "ch-drawer" : "ch-sheet"}>
        {children}
      </div>
    </div>
  );
}

/** The phone menu drawer (left, 312px): Home, New chat, the past chats grouped like the desktop sidebar. */
export function MobileDrawer({
  onClose,
  onNew,
  threads,
  currentId,
  newRow,
  now,
  onOpen,
}: {
  onClose: () => void;
  onNew: () => void;
  threads: Resource<ThreadRow[]>;
  currentId: string | null;
  newRow: { text: string; cls: string } | null;
  now: Date | null;
  onOpen: (t: ThreadRow) => void;
}) {
  return (
    <Modal onClose={onClose} label="Past chats" className="ch-drawer-root" testId="drawer">
      <div className="ch-drawer-head">
        <a href="/home" className="ch-drawer-home" data-testid="drawer-home">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M19 12H5M11 18l-6-6 6-6" />
          </svg>
          Home
        </a>
        <button type="button" className="ch-ib" onClick={onClose} aria-label="Close menu" data-testid="drawer-close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <div className="ch-drawer-new">
        <button type="button" className="ch-btn-p" onClick={onNew} data-testid="drawer-new-chat">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New chat
        </button>
      </div>
      <span className="ch-lbl ch-side-lbl">Past chats</span>
      <ThreadList threads={threads} currentId={currentId} newRow={newRow} now={now} onOpen={onOpen} />
    </Modal>
  );
}

/** The phone bottom sheet: the same facts as the desktop hover card, a 44px close button. */
export function PlayerSheet({ p, nextGw, onClose }: { p: Player; nextGw: number | null; onClose: () => void }) {
  return (
    <Modal onClose={onClose} label={`Player details: ${p.full_name}`} className="ch-sheet-root" testId="player-sheet">
      <span className="ch-sheet-handle" aria-hidden="true" />
      <div className="ch-sheet-head">
        <div>
          <span className="ch-sheet-name" data-testid="sheet-name">
            {p.full_name}
          </span>
          <span className="ch-sheet-sub">{[p.club, p.position, price(p.price)].filter(Boolean).join(" · ")}</span>
        </div>
        <button type="button" className="ch-ib" onClick={onClose} aria-label="Close player details" data-testid="sheet-close">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <PlayerFacts p={p} nextGw={nextGw} compact />
    </Modal>
  );
}

/** "4-4-2 · C HAALAND · 1 INJURY" (injury = flagged players in the fifteen). */
export function teamBarLine(card: TeamCardData): { text: string; injuries: number } {
  const captain = card.players.find((p) => p.role === "C");
  const injuries = card.players.filter((p) => p.flag).length;
  return { text: `${card.formation} · C ${(captain?.short_name ?? "—").toUpperCase()}`, injuries };
}

/** The phone team bar pinned under the header + the pitch panel it slides open (bank line + Refresh, the 250px pitch, the
 *  bench, one chips row). The panel opens itself when a preview arrives and closes when the user starts typing. */
export function MobileTeam({
  card,
  preview,
  open,
  onToggle,
  refresh,
  onRefresh,
  onRetry,
  teamName,
}: {
  card: Resource<TeamCardData>;
  preview: SquadPreview | null;
  open: boolean;
  onToggle: () => void;
  refresh: RefreshState;
  onRefresh: () => void;
  onRetry: () => void;
  teamName: string | null;
}) {
  const [sheet, setSheet] = useState<Player | null>(null);
  const data = card.status === "ready" ? card.data : null;
  const slots = useMemo(() => (data ? pitchSlots(data.players, preview) : null), [data, preview]);
  const line = data ? teamBarLine(data) : null;
  return (
    <>
      <button type="button" className="ch-teambar" onClick={onToggle} aria-expanded={open} aria-controls="m-pitch" data-testid="team-bar">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5BE3A4" strokeWidth="1.8" aria-hidden="true" style={{ flexShrink: 0 }}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 12h18" />
          <circle cx="12" cy="12" r="3" />
        </svg>
        <span className="ch-teambar-names">
          <span className="ch-teambar-name" data-testid="team-bar-name">
            {teamName ?? data?.team.name ?? "Your team"}
          </span>
          <span className="ch-teambar-line" data-testid="team-bar-line">
            {card.status === "loading" ? "Loading your team…" : card.status === "error" ? "Couldn’t load your team" : line ? (
              <>
                {line.text} · {line.injuries ? <span className="inj">{line.injuries} {line.injuries === 1 ? "INJURY" : "INJURIES"}</span> : "NO INJURIES"}
              </>
            ) : null}
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
          {card.status === "loading" && <span className="ch-sk" style={{ height: 250, borderRadius: 12 }} aria-label="Loading team" />}
          {(card.status === "error" || (card.status === "ready" && !slots)) && (
            <div className="ch-card-err" style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center", textAlign: "center", padding: "12px 0" }} data-testid="card-error">
              <b>Couldn’t load your team</b>
              <span>You can keep chatting meanwhile.</span>
              <button type="button" className="ch-btn-s" onClick={onRetry} data-testid="card-retry">
                Retry
              </button>
            </div>
          )}
          {data && slots && (
            <>
              <div className="ch-panel-top">
                <span className="line" data-testid="panel-line">
                  BANK {price(data.bank)} · {data.free_transfers ?? "?"} FT · {data.team_value === null ? "—" : price(data.team_value)} · AS OF GW{data.squad_as_of_gw}
                </span>
                <button type="button" className="ch-panel-refresh" aria-label="Refresh team" onClick={onRefresh} disabled={refresh === "busy"} data-testid="card-refresh">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M21 12a9 9 0 1 1-3-6.7" />
                    <path d="M21 4v5h-5" />
                  </svg>
                  Refresh
                </button>
              </div>
              <FplNotes card={data} refresh={refresh} />
              <Pitch slots={slots} pinnedId={null} onPick={setSheet} nextGw={data.next_gw} phone />
              <Bench slots={slots} pinnedId={null} onPick={setSheet} nextGw={data.next_gw} phone />
              <ChipsRow card={data} phone />
            </>
          )}
        </div>
      )}
      {sheet && data && <PlayerSheet p={sheet} nextGw={data.next_gw} onClose={() => setSheet(null)} />}
    </>
  );
}
