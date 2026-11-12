"use client";

import { useCallback, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ApiError, api, type DraftResult } from "@/lib/api";
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

/** One build or rebuild at a time: the building card while it runs; "Couldn't build your draft" (Try again / Cancel) on a
 *  failure; a 429 (10 an hour) or a busy server is a toast with the server's words. onDone gets the draft (and the chat to
 *  open after a first build). */
export function useDraftBuild(onDone: (r: DraftResult, kind: "build" | "rebuild") => void) {
  const { getToken } = useAuth();
  const router = useRouter();
  const [state, setState] = useState<BuildState>("idle");
  const last = useRef<"build" | "rebuild">("build");
  const run = useCallback(
    async (kind: "build" | "rebuild") => {
      last.current = kind;
      setState("building");
      try {
        const [r] = await Promise.all([kind === "build" ? api.buildDraft(getToken) : api.rebuildDraft(getToken), sleep(MIN_BUILD_MS)]);
        setState("idle");
        onDone(r, kind);
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, String(e));
        if (err.status === 401) {
          setState("idle");
          loginSignedOut(router);
        } else if (err.status === 429 || (err.status === 503 && /busy|right now/i.test(err.detail))) {
          setState("idle");
          toast.error(err.detail);
        } else {
          setState("failed");
        }
      }
    },
    [getToken, onDone, router],
  );
  return { state, build: () => run("build"), rebuild: () => run("rebuild"), retry: () => run(last.current), cancel: () => setState("idle") };
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
