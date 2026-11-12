"use client";

import type { Player, SquadChange, SquadPreview } from "@/lib/api";

const TYPE_WORD: Record<SquadChange["type"], string> = { transfer: "TRANSFER", captain: "CAPTAIN", vice_captain: "VICE-CAPTAIN", bench: "BENCH ORDER" };

export function price(p: number | null | undefined): string {
  return p === null || p === undefined ? "—" : `£${p.toFixed(1)}m`;
}
function sub(p: Player): string {
  return [p.club, p.position, price(p.price)].filter(Boolean).join(" · ");
}
function shortSub(p: Player): string {
  return [p.club, price(p.price)].filter(Boolean).join(" · ");
}

/** "EXPIRES IN {m} MIN" -> "EXPIRED" at zero (C3: nothing else changes). */
export function expiryLabel(expiresAt: string | null, now: Date | null): string {
  if (!expiresAt || !now) return "";
  const left = new Date(expiresAt).getTime() - now.getTime();
  if (!(left > 0)) return "EXPIRED";
  return `EXPIRES IN ${Math.max(1, Math.ceil(left / 60_000))} MIN`;
}

/** The squad-change preview under an answer: one change = the two-card swap, several = one row per change; the impact line
 *  (only numbers the tools computed: the gain box is omitted when pts_delta is null); Yes / No while pending, else "You
 *  chose …". */
export function PreviewCard({
  preview,
  pending,
  choice,
  now,
  phone,
  onYes,
  onNo,
}: {
  preview: SquadPreview;
  pending: boolean;
  choice: string | null;
  now: Date | null;
  phone: boolean;
  onYes: () => void;
  onNo: () => void;
}) {
  const n = preview.changes.length;
  const single = n === 1 ? preview.changes[0] : null;
  const im = preview.impact;
  const boxes: { k: string; v: string; cls?: string }[] = [];
  if (im.pts_delta !== null && im.pts_delta !== undefined) {
    const h = im.pts_horizon_gws ?? null;
    boxes.push({ k: h ? `NEXT ${h} GWS (WEIGHTED)` : "GAIN (WEIGHTED)", v: `${im.pts_delta >= 0 ? "+" : ""}${im.pts_delta.toFixed(1)} pts`, cls: im.pts_delta >= 0 ? "gain" : "loss" });
  }
  if (im.bank_after !== null && im.bank_after !== undefined) boxes.push({ k: "BANK AFTER", v: price(im.bank_after) });
  if (im.ft_before !== null && im.ft_after !== null && im.ft_before !== undefined && im.ft_after !== undefined) boxes.push({ k: "FREE TRANSFERS", v: `${im.ft_before} → ${im.ft_after}` });
  if (im.hit_pts) boxes.push({ k: "HIT", v: `-${im.hit_pts} pts`, cls: "loss" });
  // Prompt W11: a draft change is free -- one value line instead of the bank / free-transfer / hit boxes
  const draftLine = preview.draft
    ? `Value ${price(im.value_before)} → ${price(im.value_after)} · ${(im.over_after ?? 0) > 0 ? `${price(im.over_after)} over` : `${price(im.left_after)} left`}`
    : null;
  if (draftLine) boxes.length = 0;
  const label = preview.draft
    ? preview.kind === "rebuild"
      ? "Draft rebuild · preview"
      : single
        ? "Draft change · preview"
        : `Draft change · ${n} change${n === 1 ? "" : "s"}`
    : single
      ? "Squad change · preview"
      : `Squad change · ${n} change${n === 1 ? "" : "s"}`;
  const meta = preview.draft
    ? single
      ? `${TYPE_WORD[single.type]} · FREE`
      : pending
        ? expiryLabel(preview.expires_at, now)
        : "FREE"
    : single
      ? `${TYPE_WORD[single.type]}${preview.gw ? ` · GW${preview.gw}` : ""}`
      : pending
        ? expiryLabel(preview.expires_at, now)
        : preview.gw
          ? `GW${preview.gw}`
          : "";
  return (
    <section className={`ch-preview${pending ? "" : " done"}`} aria-label={pending ? "Squad change preview" : "Squad change preview (answered)"} data-testid="preview-card" data-pending={pending} data-changes={n}>
      {pending && (
        <>
          <span className="hm-br hm-tl" aria-hidden="true" />
          <span className="hm-br hm-brr" aria-hidden="true" />
        </>
      )}
      <div className="ch-preview-head">
        <span className="ch-lbl">{label}</span>
        <span className="ch-preview-meta" data-testid="preview-meta">
          {single && pending ? (
            <>
              {meta} · {expiryLabel(preview.expires_at, now)}
            </>
          ) : (
            meta
          )}
        </span>
      </div>
      {single ? (
        <div className="ch-swap">
          <div className="ch-swap-card ch-swap-out" data-testid="preview-out">
            <span className="ch-swap-k">OUT</span>
            <span className="ch-swap-name">{single.out.short_name}</span>
            <span className="ch-swap-sub">{phone ? shortSub(single.out) : sub(single.out)}</span>
          </div>
          <span className="ch-swap-arrow" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </span>
          <div className="ch-swap-card ch-swap-in" data-testid="preview-in">
            <span className="ch-swap-k">IN</span>
            <span className="ch-swap-name">{single.in.short_name}</span>
            <span className="ch-swap-sub">{phone ? shortSub(single.in) : sub(single.in)}</span>
          </div>
        </div>
      ) : (
        preview.changes.map((ch, i) => (
          <div className="ch-chg-row" key={i} data-testid="preview-row">
            <span className="ch-chg-k">{TYPE_WORD[ch.type]}</span>
            <span className="ch-pin o" title={sub(ch.out)}>
              {ch.out.short_name}
            </span>
            <span aria-hidden="true" style={{ color: "#3BE8FF" }}>
              →
            </span>
            <span className="ch-pin i" title={sub(ch.in)}>
              {ch.in.short_name}
            </span>
          </div>
        ))
      )}
      {draftLine && (
        <span className="ch-draft-impact" style={{ fontSize: 13.5, color: "#E9D6A6" }} data-testid="impact-line">
          {draftLine}
        </span>
      )}
      {boxes.length > 0 &&
        (phone ? (
          <span style={{ fontSize: 13, color: "#A9BACB" }} data-testid="impact-line">
            {boxes.map((b, i) => (
              <span key={b.k}>
                {i > 0 && " · "}
                {b.cls ? <b style={{ color: b.cls === "gain" ? "#5BE3A4" : "#FF8A7A", fontWeight: 600 }}>{b.v}</b> : b.v} {b.k.toLowerCase()}
              </span>
            ))}
          </span>
        ) : (
          <div className={`ch-impact${boxes.length === 2 ? " two" : boxes.length === 4 ? " four" : ""}`} data-testid="impact-line">
            {boxes.map((b) => (
              <div key={b.k}>
                <span>{b.k}</span>
                <b className={b.cls}>{b.v}</b>
              </div>
            ))}
          </div>
        ))}
      {pending ? (
        <div className="ch-preview-acts">
          <button type="button" className="ch-btn-p" onClick={onYes} data-testid="preview-yes">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12l5 5L20 7" />
            </svg>
            Yes, apply
          </button>
          <button type="button" className="ch-btn-s" onClick={onNo} data-testid="preview-no">
            No, keep it
          </button>
          <span className="ch-preview-hint">Shown on the pitch →</span>
        </div>
      ) : (
        choice && (
          <span className="ch-chosen" data-testid="preview-choice">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12l5 5L20 7" />
            </svg>
            You chose “{choice}”
          </span>
        )
      )}
    </section>
  );
}
