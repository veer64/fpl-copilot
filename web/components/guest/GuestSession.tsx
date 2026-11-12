"use client";

import { useState } from "react";
import { ConfirmDelete } from "@/components/account/ConfirmDelete";
import { useResource } from "@/components/home/useResource";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api, type Me } from "@/lib/api";
import { useGuestSession } from "@/lib/guest";

/** Prompt W9: everything a page shows and does for a guest -- the slim banner (Home and Chat), the 28-minute "Still there?"
 *  dialog, the end-and-sign-in confirm, and the session logic itself (pings, the desktop leave signal, the idle clock, the
 *  browser-restart check) through useGuestSession. Renders nothing for a signed-in person. `me` may be the page's own /me
 *  resource; without it the component reads /me once. */
export function GuestSession({ me: given, banner = false }: { me?: Me | null; banner?: boolean }) {
  const [own] = useResource<Me | null>(given === undefined ? api.me : noMe);
  const me = given !== undefined ? given : own.status === "ready" ? own.data : null;
  const { warning, stay, end } = useGuestSession(me);
  const [confirm, setConfirm] = useState(false);
  if (!me?.is_guest) return null;
  const mins = me.guest?.idle_minutes ?? 30;
  return (
    <>
      {banner && (
        <div className="gm-banner" role="note" data-testid="guest-banner">
          <span className="gm-banner-dot" aria-hidden="true" />
          <span className="gm-banner-text">
            <b>Guest mode</b> — everything here is deleted when you leave or after {mins} minutes idle. Sign in with Google or email for an account that keeps your chats.
          </span>
          <button type="button" className="gm-banner-link" onClick={() => setConfirm(true)} data-testid="guest-banner-sign-in">
            Sign in
          </button>
        </div>
      )}
      <ConfirmDelete
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Sign in instead?"
        intro="Signing in ends this guest session and deletes its chats."
        confirmLabel="End and sign in"
        cancelLabel="Stay"
        busyLabel="Ending…"
        errorFor={() => "Couldn’t end the guest session — try again."}
        onConfirm={async () => {
          await end();
          await new Promise(() => undefined); // the page is leaving
        }}
        testId="guest-sign-in"
      />
      <Dialog open={warning !== null} onOpenChange={(next) => !next && stay()}>
        <DialogContent className="hm-del-dialog hm-pop gm-idle" showCloseButton={false} data-testid="guest-idle-dialog">
          <div className="hm-del gm-idle-body" data-seconds-left={warning?.secondsLeft ?? ""}>
            <span className="hm-br hm-tl" aria-hidden="true" />
            <span className="hm-br hm-brr" aria-hidden="true" />
            <div className="hm-del-head">
              <span className="hm-del-ic gm-idle-ic" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 7v5l3 2" />
                </svg>
              </span>
              <div>
                <DialogTitle className="hm-del-title" data-testid="guest-idle-title">
                  Still there?
                </DialogTitle>
                <span className="hm-del-intro" data-testid="guest-idle-intro">
                  Your guest session ends in <span className="mono" data-testid="guest-idle-countdown">{clock(warning?.secondsLeft ?? 0)}</span>
                </span>
              </div>
            </div>
            <div className="hm-del-acts">
              <button type="button" className="hm-btn-p gm-idle-stay" onClick={stay} data-testid="guest-idle-stay" autoFocus>
                I’m here
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

const noMe = () => Promise.resolve(null);

function clock(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}
