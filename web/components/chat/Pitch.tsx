"use client";

import type { Player, SquadPreview } from "@/lib/api";
import { club } from "@/lib/clubs";
import { dayShort } from "@/lib/time";
import { price } from "./PreviewCard";

export type SlotState = {
  player: Player;
  /** the OUT player drawn faded behind (a transfer or an XI<->bench swap into this slot) */
  ghost: Player | null;
  /** the token's highlight: "in" (green, "IN" tag), "out" (faded red), "badge-in" / "badge-out" (an armband move) */
  mark: "in" | "out" | "badge-in" | "badge-out" | null;
  role: "C" | "VC" | null;
};

/** The pitch as drawn while a preview is pending (C2): the CURRENT squad in its slots, never re-laid out; every IN player
 *  drawn green in the OUT player's slot with the OUT faded red behind; both players of an armband move stay in place with
 *  the badge moved; a player who is both OUT and IN is drawn green (green wins). */
export function pitchSlots(players: Player[], preview: SquadPreview | null): Map<number, SlotState> {
  const slots = new Map<number, SlotState>();
  for (const p of players) if (p.slot) slots.set(p.slot, { player: p, ghost: null, mark: null, role: p.role });
  if (!preview) return slots;
  const outs = new Set<number>();
  const ins = new Set<number>();
  for (const ch of preview.changes) {
    if (ch.type === "captain" || ch.type === "vice_captain") {
      const badge = ch.type === "captain" ? "C" : "VC";
      for (const s of slots.values()) {
        if (s.player.id === ch.out.id) {
          if (s.mark !== "in" && s.mark !== "badge-in") s.mark = "badge-out"; // C2: a player both OUT and IN stays green
          if (s.role === badge) s.role = null;
        }
        if (s.player.id === ch.in.id) {
          s.mark = s.mark === "in" ? "in" : "badge-in";
          s.role = badge;
        }
      }
      continue;
    }
    if (ch.slot === null) continue;
    const target = slots.get(ch.slot);
    if (!target) continue;
    outs.add(ch.out.id);
    ins.add(ch.in.id);
    target.ghost = target.player.id === ch.out.id ? target.player : ch.out;
    target.player = { ...ch.in, slot: ch.slot };
    target.mark = "in";
    target.role = target.role ?? ch.in.role;
    // the IN player's own current token (a bench player entering the XI) leaves its slot
    for (const [k, s] of slots) if (k !== ch.slot && s.player.id === ch.in.id && s.mark !== "in") s.mark = "out";
  }
  for (const s of slots.values()) if (outs.has(s.player.id) && !ins.has(s.player.id) && s.mark === null) s.mark = "out";
  return slots;
}

export function formationRows(slots: Map<number, SlotState>): SlotState[][] {
  const xi = [...slots.entries()].filter(([k]) => k <= 11).sort((a, b) => a[0] - b[0]).map(([, s]) => s);
  const by: Record<string, SlotState[]> = { GK: [], DEF: [], MID: [], FWD: [] };
  for (const s of xi) by[s.player.position ?? "MID"].push(s);
  return [by.GK, by.DEF, by.MID, by.FWD].filter((r) => r.length);
}
export function benchRow(slots: Map<number, SlotState>): SlotState[] {
  return [12, 13, 14, 15].map((k) => slots.get(k)).filter((s): s is SlotState => !!s);
}

function flagClass(p: Player): string {
  const c = p.flag?.chance;
  return c !== null && c !== undefined && c <= 25 ? "ch-flag ch-flag-r" : "ch-flag ch-flag-y";
}
function flagText(p: Player): string {
  const c = p.flag?.chance;
  return c === null || c === undefined ? "!" : `${c}%`;
}
export function playingText(p: Player): string {
  const c = p.flag?.chance;
  return c === null || c === undefined ? "100%" : `${c}%`;
}
export function nextLong(p: Player): string {
  if (!p.next) return "No fixture";
  return `${club(p.next.opp).name} (${p.next.home ? "H" : "A"})`;
}

function Strip({ p }: { p: Player }) {
  if (!p.next) return <span className="ch-nf blank">—</span>;
  const c = club(p.next.opp);
  return (
    <span className="ch-nf" style={{ background: c.bg, color: c.fg }} data-testid="fixture-strip" data-opp={c.code} data-home={p.next.home}>
      {c.code}
      <i>{p.next.home ? "H" : "A"}</i>
    </span>
  );
}

/** The compact player card: full name; club · pos · price; the injury line when flagged; PRED (FPL EST. when the source is
 *  FPL's estimate) / PLAYING / AVG PTS; the next fixture. Shared by the desktop hover card and the phone sheet. */
export function PlayerFacts({ p, nextGw, compact }: { p: Player; nextGw: number | null; compact: boolean }) {
  const predLbl = p.pred ? (p.pred.source === "fpl_est" ? "FPL EST." : `PRED. GW${nextGw ?? ""}`.trim()) : "PRED.";
  const red = p.flag?.chance !== null && p.flag?.chance !== undefined && p.flag.chance <= 25;
  return (
    <>
      {p.flag && (
        <span className={`ch-pop-flag${red ? " r" : ""}`} data-testid="hover-flag">
          {[playingText(p), p.flag.news?.split(" - ")[0] ?? null, dayShort(p.flag.news_date)].filter(Boolean).join(" · ")}
        </span>
      )}
      <div className="ch-pop-st">
        <div>
          <b className="pred" data-testid="hover-pred">{p.pred ? p.pred.points.toFixed(1) : "—"}</b>
          <span data-testid="hover-pred-label">{predLbl}</span>
        </div>
        <div>
          <b data-testid="hover-playing">{playingText(p)}</b>
          <span>PLAYING</span>
        </div>
        <div>
          <b data-testid="hover-form">{p.form === null ? "—" : p.form.toFixed(1)}</b>
          <span>AVG PTS</span>
        </div>
      </div>
      <span className="ch-pop-next" data-testid="hover-next">
        Next: <em>{p.next ? club(p.next.opp).name : "no fixture"}</em>
        {p.next ? ` (${p.next.home ? "H" : "A"})` : ""}
      </span>
      {compact && null}
    </>
  );
}

export function tokenLabel(s: SlotState, bench: string | null): string {
  const p = s.player;
  const nxt = p.next ? `, next ${club(p.next.opp).name} ${p.next.home ? "at home" : "away"}` : "";
  const role = s.role === "C" ? ", captain" : s.role === "VC" ? ", vice-captain" : "";
  return `${bench ? `Bench ${bench}: ` : ""}${p.full_name}${role}${nxt}`;
}

/** One token (66px): short name, the next-fixture strip in the opponent's colours, C / VC badge, flag pill, and the preview
 *  marks; the hover card opens on hover / focus / tap, below for the top two rows else above, aligned to stay inside. */
export function Token({
  s,
  vert,
  horiz,
  pinned,
  onPick,
  nextGw,
  bench,
  phone,
}: {
  s: SlotState;
  vert: "below" | "above";
  horiz: "al" | "ac" | "ar";
  pinned: boolean;
  onPick: () => void;
  nextGw: number | null;
  bench: string | null;
  phone: boolean;
}) {
  const p = s.player;
  const popId = `pop-${bench ? "b" : "x"}-${p.id}`;
  const cls = ["ch-tok", s.mark === "in" ? "inn" : s.mark === "out" ? "out" : s.mark === "badge-in" ? "badge-in" : s.mark === "badge-out" ? "badge-out" : "", pinned ? "sel" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="ch-tw">
      {s.ghost && (
        <div className="ch-tok out ghost" aria-hidden="true" data-testid="token-ghost" data-player-id={s.ghost.id}>
          <span className="ch-tok-name">{s.ghost.short_name}</span>
          <Strip p={s.ghost} />
          <span className="ch-swaptag ch-st-out">OUT</span>
        </div>
      )}
      <button
        type="button"
        className={cls}
        onClick={onPick}
        aria-describedby={phone ? undefined : popId}
        aria-pressed={pinned || undefined}
        data-testid="token"
        data-player-id={p.id}
        data-slot={p.slot ?? ""}
        data-mark={s.mark ?? ""}
        data-role={s.role ?? ""}
      >
        {p.flag && <span className={flagClass(p)} data-testid="token-flag">{flagText(p)}</span>}
        {s.role === "C" && (
          <span className="ch-badge-c" data-testid="badge-c">
            C
          </span>
        )}
        {s.role === "VC" && (
          <span className="ch-badge-vc" data-testid="badge-vc">
            VC
          </span>
        )}
        {bench && phone && <span className="ch-bn-tag">{bench}</span>}
        <span className="ch-tok-name">{p.short_name}</span>
        <Strip p={p} />
        {s.mark === "in" && <span className="ch-swaptag ch-st-in">IN</span>}
        {/* the accessible name is the content (WCAG 2.5.3: the visible text is part of the name) + this hidden detail */}
        <span className="ch-sr">{`: ${tokenLabel(s, bench)}${phone ? " — details" : ""}`}</span>
      </button>
      {!phone && (
        <div className={`ch-pop ${vert} ${horiz}${pinned ? " show" : ""}`} role="tooltip" id={popId} data-testid="hover-card">
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <span className="ch-pop-name">{p.full_name}</span>
            <span className="ch-pop-sub">{[p.club, p.position, price(p.price)].filter(Boolean).join(" · ")}</span>
          </div>
          <PlayerFacts p={p} nextGw={nextGw} compact={false} />
        </div>
      )}
    </div>
  );
}

export function horizFor(i: number, n: number): "al" | "ac" | "ar" {
  return n % 2 === 1 && i === (n - 1) / 2 ? "ac" : i < n / 2 ? "al" : "ar";
}

/** The pitch: stripes, lines, the cyan grid, the XI in formation rows (GK top -> FWD bottom). */
export function Pitch({
  slots,
  pinnedId,
  onPick,
  nextGw,
  phone,
}: {
  slots: Map<number, SlotState>;
  pinnedId: number | null;
  onPick: (p: Player) => void;
  nextGw: number | null;
  phone: boolean;
}) {
  const rows = formationRows(slots);
  return (
    <div className="ch-pitch" data-testid="pitch">
      <div className="ch-pitch-bg" aria-hidden="true">
        <div className="ch-pitch-grid" />
        <div className="ch-pl" style={{ inset: 8, borderRadius: 4 }} />
        <div className="ch-pl" style={{ left: 8, right: 8, top: "50%", height: 0, borderWidth: "1.5px 0 0" }} />
        <div className="ch-pl" style={{ left: "50%", top: "50%", width: phone ? 60 : 70, height: phone ? 60 : 70, margin: phone ? "-30px 0 0 -30px" : "-35px 0 0 -35px", borderRadius: "50%" }} />
        <div className="ch-pl" style={{ left: "50%", top: 8, width: 150, height: phone ? 40 : 52, marginLeft: -75, borderTop: 0 }} />
        {!phone && <div className="ch-pl" style={{ left: "50%", top: 8, width: 70, height: 20, marginLeft: -35, borderTop: 0 }} />}
        <div className="ch-pl" style={{ left: "50%", bottom: 8, width: 150, height: phone ? 40 : 52, marginLeft: -75, borderBottom: 0 }} />
        {!phone && <div className="ch-pl" style={{ left: "50%", bottom: 8, width: 70, height: 20, marginLeft: -35, borderBottom: 0 }} />}
      </div>
      <div className="ch-rows">
        {rows.map((row, ri) => (
          <div className={`ch-prow${row.length >= 5 ? " five" : ""}`} key={ri} data-testid="pitch-row" data-n={row.length}>
            {row.map((s, i) => (
              <Token key={s.player.id} s={s} vert={ri < 2 ? "below" : "above"} horiz={horizFor(i, row.length)} pinned={pinnedId === s.player.id} onPick={() => onPick(s.player)} nextGw={nextGw} bench={null} phone={phone} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Bench({ slots, pinnedId, onPick, nextGw, phone }: { slots: Map<number, SlotState>; pinnedId: number | null; onPick: (p: Player) => void; nextGw: number | null; phone: boolean }) {
  const bench = benchRow(slots);
  if (phone) {
    return (
      <div className="ch-panel-bench" data-testid="bench">
        {bench.map((s, i) => (
          <Token key={s.player.id} s={s} vert="above" horiz={horizFor(i, 4)} pinned={pinnedId === s.player.id} onPick={() => onPick(s.player)} nextGw={nextGw} bench={i === 0 ? "GK" : String(i)} phone />
        ))}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="ch-bench-lbl">BENCH · IN ORDER</span>
      <div className="ch-bench" data-testid="bench">
        {bench.map((s, i) => (
          <div className="ch-bench-slot" key={s.player.id}>
            <Token s={s} vert="above" horiz={horizFor(i, 4)} pinned={pinnedId === s.player.id} onPick={() => onPick(s.player)} nextGw={nextGw} bench={i === 0 ? "GK" : String(i)} phone={false} />
            <span className="ch-bn">{i === 0 ? "GK" : i}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
