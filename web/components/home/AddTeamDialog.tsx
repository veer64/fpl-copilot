"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@clerk/nextjs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { ApiError, api, parseTeamInput, type TeamCard } from "@/lib/api";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";
import { Spinner } from "./TeamCard";

/** The Add team flow (BRIEF "Add team flow"): a Dialog on desktop, a bottom Drawer on narrow screens; one field for the
 *  ID or a pasted link, an optional label, the "How do I find my team ID?" helper, every state and error of the brief. */

export const ADD_COPY = {
  invalid: "That’s not a valid ID or FPL link",
  notFound: "We couldn’t find that team ID",
  duplicate: "You’ve already added this team",
  limit: "You can add up to 3 teams",
  unavailable: "FPL isn’t responding right now — try again in a minute",
  fetching: "Fetching your team from FPL…",
  success: "Your squad is shown as of the last deadline; transfers since then appear after the next one.",
} as const;

/** The backend's refusal as the brief's sentence. */
export function addTeamError(err: unknown): string {
  if (!(err instanceof ApiError)) return ADD_COPY.unavailable;
  switch (err.status) {
    case 404:
      return ADD_COPY.notFound;
    case 409:
      if (/already added/i.test(err.detail)) return ADD_COPY.duplicate;
      if (/up to 3/i.test(err.detail)) return ADD_COPY.limit;
      return err.detail; // e.g. "this FPL team has no picks yet" -- the backend's own words
    case 422:
      return ADD_COPY.invalid;
    case 429:
      return err.detail;
    default:
      return ADD_COPY.unavailable;
  }
}

function UrlBarIllustration() {
  return (
    <svg
      className="hm-urlbar"
      viewBox="0 0 400 44"
      role="img"
      aria-label="A browser address bar reading fantasy.premierleague.com/entry/1234567/event/9, with 1234567 highlighted"
    >
      <rect x="1" y="1" width="398" height="42" rx="12" fill="#0B1520" stroke="#24384A" />
      <circle cx="18" cy="22" r="4" fill="#2C4052" />
      <circle cx="30" cy="22" r="4" fill="#2C4052" />
      <circle cx="42" cy="22" r="4" fill="#2C4052" />
      <rect x="58" y="9" width="330" height="26" rx="8" fill="rgba(255,255,255,0.04)" stroke="#1E2F3E" />
      <rect x="255" y="12" width="66" height="20" rx="5" fill="rgba(59,232,255,0.22)" stroke="#3BE8FF" />
      <text x="68" y="26" fontFamily="ui-monospace, monospace" fontSize="11.5" fill="#A9BACB">
        fantasy.premierleague.com/entry/
        <tspan fill="#F2FBFF" fontWeight="600">
          1234567
        </tspan>
        /event/9
      </text>
    </svg>
  );
}

function AddTeamForm({
  titleId,
  onDone,
  onCancel,
}: {
  titleId: string;
  onDone: (card: TeamCard) => void;
  onCancel: () => void;
}) {
  const { getToken } = useAuth();
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const id = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const id = parseTeamInput(value);
    if (id === null) {
      setError(ADD_COPY.invalid);
      inputRef.current?.focus();
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const card = await api.addTeam(getToken, id, label.trim() || undefined);
      onDone(card);
    } catch (err) {
      setError(addTeamError(err));
      setBusy(false);
      window.requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  return (
    <form onSubmit={submit} noValidate className="hm-form" aria-busy={busy} data-testid="add-team-form">
      <span className="hm-eyebrow">YOUR TEAMS</span>
      <h2 id={titleId}>Add an FPL team</h2>
      <div className="hm-field">
        <label htmlFor="add-team-id">FPL team ID or link</label>
        <input
          id="add-team-id"
          ref={inputRef}
          className="hm-input"
          type="text"
          inputMode="text"
          autoComplete="off"
          placeholder="1234567 or fantasy.premierleague.com/entry/1234567/…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={busy}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "add-team-error" : undefined}
          data-testid="add-team-input"
        />
        {error && (
          <p id="add-team-error" className="hm-alert" role="alert" data-testid="add-team-error">
            {error}
          </p>
        )}
      </div>
      <div className="hm-field">
        <label htmlFor="add-team-label">
          Label <span style={{ color: "#8A9BB0", fontWeight: 400 }}>(optional)</span>
        </label>
        <input
          id="add-team-label"
          className="hm-input"
          type="text"
          autoComplete="off"
          placeholder="My main team"
          maxLength={40}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          disabled={busy}
          data-testid="add-team-label"
        />
      </div>
      <Collapsible open={helpOpen} onOpenChange={setHelpOpen}>
        <CollapsibleTrigger className="hm-help-btn" data-testid="help-toggle">
          How do I find my team ID?
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </CollapsibleTrigger>
        <CollapsibleContent className="hm-help" data-testid="help-panel">
          <UrlBarIllustration />
          <ol>
            <li>Open fantasy.premierleague.com and log in.</li>
            <li>
              Click <strong>Points</strong>.
            </li>
            <li>
              Your ID is the number after <strong>/entry/</strong> in the address bar.
            </li>
          </ol>
          <p>Tip: or just paste the whole link. Note: in the FPL phone app the ID is hard to find — use the website.</p>
        </CollapsibleContent>
      </Collapsible>
      <div className="hm-form-actions">
        <button type="submit" className="hm-btn-p" disabled={busy} data-testid="add-team-submit">
          {busy ? (
            <>
              <Spinner /> {ADD_COPY.fetching}
            </>
          ) : (
            "Add team"
          )}
        </button>
        <button type="button" className="hm-cancel" onClick={onCancel} disabled={busy} data-testid="add-team-cancel">
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Prompt W11 (brief 3c): at the bottom of the dialog, after a divider, the amber link "Don't have an FPL team? Build one ->"
 *  (it closes the dialog and starts the build) -- or "Open your draft ->" once a draft exists. null: no link. */
export type DraftLink = { kind: "build" | "open"; onClick: () => void } | null;

function DraftLinkRow({ link, close }: { link: DraftLink; close: () => void }) {
  if (!link) return null;
  return (
    <div className="hm-add-link">
      <button
        type="button"
        className="dr-link"
        onClick={() => {
          close();
          link.onClick();
        }}
        data-testid="add-team-draft-link"
        data-kind={link.kind}
      >
        {link.kind === "build" ? "Don’t have an FPL team? Build one" : "Open your draft"}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </div>
  );
}

export function AddTeamDialog({
  open,
  onOpenChange,
  onAdded,
  draftLink = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (card: TeamCard) => void;
  draftLink?: DraftLink;
}) {
  const narrow = useMediaQuery(NARROW);
  const done = (card: TeamCard) => {
    onOpenChange(false);
    onAdded(card);
  };
  const close = () => onOpenChange(false);
  if (narrow) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} swipeDirection="down" showSwipeHandle>
        <DrawerContent className="hm-sheet" aria-labelledby="add-team-title" data-testid="add-team-sheet">
          <div className="hm-sheet-in">
            <span className="hm-br hm-tl" aria-hidden="true" />
            <DrawerTitle className="sr-only">Add an FPL team</DrawerTitle>
            <AddTeamForm titleId="add-team-title" onDone={done} onCancel={() => onOpenChange(false)} />
            <DraftLinkRow link={draftLink} close={close} />
          </div>
        </DrawerContent>
      </Drawer>
    );
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="hm-dialog hm-pop" showCloseButton={false} aria-labelledby="add-team-title" data-testid="add-team-dialog">
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        <AddTeamForm titleId="add-team-title" onDone={done} onCancel={() => onOpenChange(false)} />
        <DraftLinkRow link={draftLink} close={close} />
      </DialogContent>
    </Dialog>
  );
}
