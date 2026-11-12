"use client";

import { useRef } from "react";
import { toast } from "sonner";
import type { DraftCard, Player } from "@/lib/api";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";
import { DraftBadge, money } from "./DraftParts";

/** Prompt W11 (brief section 7): "Enter your draft in FPL" -- the 15 grouped GK / DEF / MID / FWD (starters first, bench
 *  marked BENCH, the same C / VC badges as the pitch, prices at current prices), "Copy list", five plain-text steps (no FPL
 *  logos or screenshots), "Add my team ID" opening the existing Add team dialog, and the price note. A dialog on desktop, a
 *  bottom sheet on the phone. */

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;
const WORDS: Record<(typeof POSITIONS)[number], string> = { GK: "GOALKEEPERS", DEF: "DEFENDERS", MID: "MIDFIELDERS", FWD: "FORWARDS" };

function grouped(players: Player[]) {
  return POSITIONS.map((pos) => ({
    pos,
    rows: players
      .filter((p) => p.position === pos)
      .sort((a, b) => ((a.slot ?? 99) > 11 ? 1 : 0) - ((b.slot ?? 99) > 11 ? 1 : 0) || (a.slot ?? 99) - (b.slot ?? 99)),
  }));
}

const isBench = (p: Player) => (p.slot ?? 0) > 11;

/** The plain-text list "Copy list" puts on the clipboard: position, name, club, price, C / VC (and BENCH). */
export function plainList(d: DraftCard): string {
  const lines = [`My FPL Copilot draft — ${money(d.value)} of ${money(d.budget)}`];
  for (const g of grouped(d.players)) {
    for (const p of g.rows) {
      const tags = [p.role === "C" ? "C" : p.role === "VC" ? "VC" : null, isBench(p) ? "BENCH" : null].filter(Boolean).join(" ");
      lines.push(`${g.pos.padEnd(3)} ${p.short_name} (${p.full_name}) · ${p.club ?? "?"} · ${money(p.price)}${tags ? ` · ${tags}` : ""}`);
    }
  }
  return lines.join("\n");
}

function Body({ d, onAddTeam, Title }: { d: DraftCard; onAddTeam: () => void; Title: typeof DialogTitle | typeof DrawerTitle }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plainList(d));
      toast("List copied");
    } catch {
      toast.error("Couldn’t copy the list");
    }
  };
  const over = (d.over ?? 0) > 0;
  return (
    <>
      <Title className="dr-guide-title" id="dr-guide-t">
        Enter your draft in FPL <DraftBadge small />
      </Title>
      <div className="dr-guide-body">
        {grouped(d.players).map((g) => (
          <div className="dr-grp" key={g.pos} role="group" aria-label={WORDS[g.pos].toLowerCase()}>
            <span className="dr-grp-h">{WORDS[g.pos]}</span>
            {g.rows.map((p) => (
              <div className="dr-grow" key={p.id} data-testid="guide-row" data-bench={isBench(p)}>
                <span className="nm" title={p.full_name}>
                  {p.short_name}
                </span>
                {p.role && (
                  <span className={`dr-cv ${p.role === "C" ? "c" : "vc"}`} aria-label={p.role === "C" ? "captain" : "vice-captain"}>
                    {p.role}
                  </span>
                )}
                {isBench(p) && <span className="bench">BENCH</span>}
                <span className="club">{p.club}</span>
                <span className="pr">{money(p.price)}</span>
              </div>
            ))}
          </div>
        ))}
        <div className="dr-total">
          <span data-testid="guide-total" className={over ? "dr-over" : undefined}>
            {money(d.value)} of {money(d.budget)}
            {over ? ` · ${money(d.over)} over` : ""}
          </span>
          <button type="button" className="dr-copy" onClick={copy} data-testid="guide-copy">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15V5a1 1 0 0 1 1-1h10" />
            </svg>
            Copy list
          </button>
        </div>
        <ol className="dr-steps" data-testid="guide-steps">
          <li>
            Go to <strong>fantasy.premierleague.com</strong> and sign in (or create an account).
          </li>
          <li>Create your team with these 15.</li>
          <li>Save it.</li>
          <li>
            Open the <strong>Points</strong> tab and copy the link from the address bar.
          </li>
          <li>
            Add it here:
            <br />
            <button type="button" className="hm-btn-o" onClick={onAddTeam} data-testid="guide-add-team">
              Add my team ID
            </button>
          </li>
        </ol>
        <div className="dr-note" role="note">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FFC23D" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }}>
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8h.01M11 12h1v5h1" />
          </svg>
          FPL prices change daily. If a player now costs more and the 15 don’t fit, ask me for a swap.
        </div>
      </div>
    </>
  );
}

export function EnterGuide({ d, open, onClose, onAddTeam }: { d: DraftCard | null; open: boolean; onClose: () => void; onAddTeam: () => void }) {
  const narrow = useMediaQuery(NARROW);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  if (!d) return null;
  const close = (
    <button type="button" className="ch-ib" onClick={onClose} aria-label="Close the guide" ref={closeRef} data-testid="guide-close" style={{ position: "absolute", top: 14, right: 14 }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <path d="M6 6l12 12M18 6L6 18" />
      </svg>
    </button>
  );
  if (narrow) {
    return (
      <Drawer open={open} onOpenChange={(o) => !o && onClose()} swipeDirection="down" showSwipeHandle>
        <DrawerContent className="hm-sheet" aria-labelledby="dr-guide-t" data-testid="guide-sheet">
          <div className="dr-sheet-in" style={{ position: "relative" }}>
            {close}
            <Body d={d} onAddTeam={onAddTeam} Title={DrawerTitle} />
          </div>
        </DrawerContent>
      </Drawer>
    );
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="hm-dialog dr-dlg dr-guide" showCloseButton={false} aria-labelledby="dr-guide-t" data-testid="guide-dialog">
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        {close}
        <Body d={d} onAddTeam={onAddTeam} Title={DialogTitle} />
      </DialogContent>
    </Dialog>
  );
}
