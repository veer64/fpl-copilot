"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { ApiError, api, type DraftResult } from "@/lib/api";
import { useNow } from "@/components/home/useResource";
import { leftClock } from "@/lib/time";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";
import { loginSignedOut } from "@/lib/session";
import { RuleChips, RebuildIcon } from "./DraftParts";

/** Prompt W11 (brief section 5 + checkpoint default 6): building takes 0.1-1 s here, so the building card stays at least
 *  MIN_BUILD_MS so the 15 dots can pop in (reduced motion: all dots at once). */
export const MIN_BUILD_MS = 1200;
const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

export type BuildState = "idle" | "building" | "failed";

/** Prompt P3: a refused build, mapped from the HTTP status (and the body's error_kind where one status means two things) --
 *  never the server's words. `hourly`: 429 draft_limited, the 10 builds + rebuilds in a rolling hour (`untilMs` only when
 *  the response carries a Retry-After the browser may read; else the note says "within the hour"). `rate`: any other 429
 *  (the per-minute request limit). `busy`: 503 draft_busy (a third build at once). Anything else is the failed dialog. */
export type DraftNotice = { kind: "hourly"; untilMs: number | null } | { kind: "rate"; untilMs: number } | { kind: "busy" };

export function draftNotice(err: ApiError, nowMs: number = Date.now()): DraftNotice | null {
  if (err.status === 429) {
    if (err.errorKind === "draft_limited") return { kind: "hourly", untilMs: err.retryAfter !== undefined ? nowMs + err.retryAfter * 1000 : null };
    return { kind: "rate", untilMs: nowMs + (err.retryAfter ?? 60) * 1000 };
  }
  if (err.status === 503 && err.errorKind === "draft_busy") return { kind: "busy" };
  return null;
}

/** One build or rebuild at a time: the building card while it runs; "Couldn't build your draft" (Try again / Cancel) on a
 *  failure; a refusal (P3: the hourly limit, the request limit, a busy server) is `notice` -- an amber note the page shows,
 *  never a toast -- and goes to `onNotice` too (a draft chat puts it in the thread). The next build clears it. onDone gets
 *  the draft (and the chat to open after a first build). */
export function useDraftBuild(onDone: (r: DraftResult, kind: "build" | "rebuild") => void, onNotice?: (n: DraftNotice) => void) {
  const { getToken } = useAuth();
  const router = useRouter();
  const [state, setState] = useState<BuildState>("idle");
  const [notice, setNotice] = useState<DraftNotice | null>(null);
  const last = useRef<"build" | "rebuild">("build");
  const run = useCallback(
    async (kind: "build" | "rebuild") => {
      last.current = kind;
      setNotice(null);
      setState("building");
      try {
        const [r] = await Promise.all([kind === "build" ? api.buildDraft(getToken) : api.rebuildDraft(getToken), sleep(MIN_BUILD_MS)]);
        setState("idle");
        onDone(r, kind);
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, String(e));
        const refused = draftNotice(err);
        if (err.status === 401) {
          setState("idle");
          loginSignedOut(router);
        } else if (refused) {
          setState("idle");
          setNotice(refused);
          onNotice?.(refused);
        } else {
          setState("failed");
        }
      }
    },
    [getToken, onDone, onNotice, router],
  );
  const clearNotice = useCallback(() => setNotice(null), []);
  return { state, notice, clearNotice, build: () => run("build"), rebuild: () => run("rebuild"), retry: () => run(last.current), cancel: () => setState("idle") };
}

const ClockIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);
const HourglassIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 3h12M6 21h12M7 3c0 5 10 5 10 9s-10 4-10 9M17 3c0 5-10 5-10 9" />
  </svg>
);

/** Prompt P3: a refused build as the amber note the other caps use (the chat's .ch-sys look: `limit` for the hourly cap,
 *  `rate` for a short wait) -- Home shows it under the greeting, a draft chat in its thread. A countdown runs only when the
 *  wait is known; when it ends the line says so, and `onExpired` (Home) clears the note. `reveal` (Home): a note that
 *  appears off screen -- the phone's Build button sits below the fold -- is scrolled into view. */
export function DraftLimitNote({ notice, onExpired, reveal = false }: { notice: DraftNotice; onExpired?: () => void; reveal?: boolean }) {
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!reveal || !el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight) {
      el.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  }, [reveal, notice]);
  const until = notice.kind === "busy" ? null : notice.untilMs;
  const now = useNow(until !== null ? 1000 : 60_000);
  const over = until !== null && now !== null && now.getTime() >= until;
  useEffect(() => {
    if (over) onExpired?.();
  }, [over, onExpired]);
  const wait = (lead: string, again: string) =>
    until === null ? null : over ? (
      `${again} now.`
    ) : (
      <>
        {lead}{" "}
        <span className="mono" data-testid="draft-limit-countdown">
          {now ? leftClock(until, now.getTime()) : "…"}
        </span>
        .
      </>
    );
  let title: string;
  let line: ReactNode;
  if (notice.kind === "hourly") {
    title = "You’ve reached the hourly limit for building drafts.";
    line = wait("You can build or rebuild again in", "You can build or rebuild again") ?? "You can build or rebuild again within the hour.";
  } else if (notice.kind === "rate") {
    title = "Too many requests — wait a minute.";
    line = wait("You can try again in", "You can try again");
  } else {
    title = "Lots of drafts are being built right now.";
    line = "Nothing was changed — try again in a moment.";
  }
  return (
    <div ref={box} className={`ch-sys ${notice.kind === "hourly" ? "limit" : "rate"} dr-limit-note`} role="status" data-testid="draft-limit-note" data-kind={notice.kind}>
      <span className="ch-sys-ic">{notice.kind === "hourly" ? <ClockIcon /> : <HourglassIcon />}</span>
      <div className="ch-sys-body">
        <div>
          <b>{title}</b>
          <p>{line}</p>
        </div>
      </div>
    </div>
  );
}

function Dots() {
  // 11 on the pitch (1 / 4 / 4 / 2) + 4 on the bench strip, popping in one by one (aria-hidden: the status line speaks)
  const rows = [1, 4, 4, 2];
  let n = 0;
  return (
    <div aria-hidden="true" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="dr-mpitch">
        <div className="line" />
        <div className="half" />
        <div className="rows">
          {rows.map((k, r) => (
            <div key={r}>
              {Array.from({ length: k }, () => {
                const d = (n++ * 0.07).toFixed(2);
                return <span key={d} className="dr-dot" style={{ animationDelay: `${d}s` }} data-testid="build-dot" />;
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="dr-strip">
        {[0, 1, 2, 3].map(() => {
          const d = (n++ * 0.07).toFixed(2);
          return <span key={d} className="dr-dot" style={{ animationDelay: `${d}s` }} data-testid="build-dot" />;
        })}
      </div>
    </div>
  );
}

/** "Building your draft…" -- a modal glass card with amber brackets; role="status"; it cannot be dismissed. */
export function BuildingDialog({ open, rebuild }: { open: boolean; rebuild?: boolean }) {
  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent className="hm-dialog dr-dlg" showCloseButton={false} data-testid="draft-building" aria-labelledby="dr-bld-t">
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        <Dots />
        <div role="status" aria-live="polite" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <DialogTitle className="dr-bld-t" id="dr-bld-t">
            <span className="dr-spin" aria-hidden="true" />
            {rebuild ? "Rebuilding your draft…" : "Building your draft…"}
          </DialogTitle>
          <span className="dr-bld-s">Picking the best 15 from our predictions.</span>
        </div>
        <RuleChips />
      </DialogContent>
    </Dialog>
  );
}

/** "Couldn't build your draft" -- Cancel goes back, Try again repeats the build. */
export function BuildFailedDialog({ open, onCancel, onRetry }: { open: boolean; onCancel: () => void; onRetry: () => void }) {
  const retryRef = useRef<HTMLButtonElement | null>(null);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="hm-dialog dr-dlg red" showCloseButton={false} role="alertdialog" initialFocus={retryRef} aria-labelledby="dr-bf-t" aria-describedby="dr-bf-d" data-testid="draft-failed">
        <div className="dr-dlg-head">
          <span className="dr-dlg-ic red" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 3l9 16H3z" />
              <path d="M12 10v4M12 17h.01" />
            </svg>
          </span>
          <div>
            <DialogTitle className="dr-dlg-title" id="dr-bf-t">
              Couldn’t build your draft
            </DialogTitle>
            <p className="dr-dlg-text" id="dr-bf-d">
              Something went wrong while picking the 15. Nothing was saved.
            </p>
          </div>
        </div>
        <div className="dr-dlg-acts">
          <button type="button" className="hm-del-cancel" onClick={onCancel} data-testid="draft-failed-cancel">
            Cancel
          </button>
          <button type="button" className="dr-btnp" onClick={onRetry} ref={retryRef} data-testid="draft-failed-retry">
            Try again
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** "Rebuild from the best picks?" -- the same confirm on Home and in the chat (alertdialog; a sheet on the phone). Focus
 *  starts on "Keep my draft"; Esc / Keep close; focus returns to the opener. */
export function RebuildConfirm({ open, onClose, onConfirm, returnTo }: { open: boolean; onClose: () => void; onConfirm: () => void; returnTo?: React.RefObject<HTMLElement | null> }) {
  const narrow = useMediaQuery(NARROW);
  const keepRef = useRef<HTMLButtonElement | null>(null);
  const body = (Title: typeof DialogTitle | typeof DrawerTitle) => (
    <>
      <div className="dr-dlg-head">
        <span className="dr-dlg-ic amb" aria-hidden="true">
          <RebuildIcon size={18} />
        </span>
        <div>
          <Title className="dr-dlg-title" id="dr-rb-t">
            Rebuild from the best picks?
          </Title>
          <p className="dr-dlg-text" id="dr-rb-d">
            We’ll pick a fresh 15 from our latest predictions. This replaces the changes you’ve made to your draft.
          </p>
        </div>
      </div>
      <div className="dr-dlg-acts">
        <button type="button" className="hm-del-cancel" onClick={onClose} ref={keepRef} data-testid="rebuild-keep">
          Keep my draft
        </button>
        <button
          type="button"
          className="dr-btnp"
          onClick={() => {
            onClose();
            onConfirm();
          }}
          data-testid="rebuild-confirm"
        >
          <RebuildIcon />
          Rebuild
        </button>
      </div>
    </>
  );
  if (narrow) {
    return (
      <Drawer open={open} onOpenChange={(o) => !o && onClose()} swipeDirection="down">
        <DrawerContent className="hm-del-sheet" role="alertdialog" initialFocus={keepRef} finalFocus={returnTo} aria-labelledby="dr-rb-t" aria-describedby="dr-rb-d" data-testid="rebuild-confirm-sheet">
          <div className="hm-del phone" style={{ gap: 16 }}>
            <span className="hm-del-handle" aria-hidden="true" />
            {body(DrawerTitle)}
          </div>
        </DrawerContent>
      </Drawer>
    );
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="hm-dialog dr-dlg" showCloseButton={false} role="alertdialog" initialFocus={keepRef} finalFocus={returnTo} aria-labelledby="dr-rb-t" aria-describedby="dr-rb-d" data-testid="rebuild-confirm-dialog">
        <span className="hm-br hm-tl" aria-hidden="true" />
        <span className="hm-br hm-brr" aria-hidden="true" />
        {body(DialogTitle)}
      </DialogContent>
    </Dialog>
  );
}
