"use client";

/** Prompt W9 (2026-11-12): the guest session on the client. USER DECISIONS (12 Nov): a guest is deleted ~2 minutes after
 *  the last FPL Copilot tab closes on a computer (a refresh or a second tab is not closing), or after GUEST_IDLE_MINUTES
 *  (30) without a click, key, scroll or touch -- whichever comes first; at 28 minutes a "Still there?" dialog; on a phone
 *  ((pointer: coarse)) NO leave signal is sent -- switching apps must not end the session, only the idle rule and a full
 *  browser restart (the fpl_guest session cookie is gone) do. The server's reaper is the backstop (+1 minute); this file
 *  ends the session itself at 30:00 (DELETE /me, sign out, /login?reason=guest_ended).
 *  Pings: POST /me/ping at most once a minute while the user interacts, on mount and when the tab becomes visible.
 *  Tabs: every open tab writes a heartbeat into localStorage every 20 s; a closing tab sends POST /me/leave (fetch keepalive)
 *  only when no other tab beat in the last 60 s. */
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, type Me } from "./api";
import { loginGuestEndedUrl } from "./redirects";

export const GUEST_COOKIE = "fpl_guest";
const TAB_PREFIX = "fpl.guest.tab.";
const TAB_BEAT_MS = 20_000;
const TAB_STALE_MS = 60_000;
const PING_EVERY_MS = 60_000;
const WARN_BEFORE_MS = 2 * 60_000;
const TOKEN_WAIT_MS = 8000;
const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = ["pointerdown", "keydown", "wheel", "touchstart", "scroll"];

export function hasGuestCookie(): boolean {
  if (typeof document === "undefined") return true;
  return document.cookie.split(";").some((c) => c.trim().startsWith(`${GUEST_COOKIE}=`));
}

/** A session cookie (no expiry: it dies when the browser closes); Secure on https. */
export function setGuestCookie(): void {
  const secure = typeof window !== "undefined" && window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${GUEST_COOKIE}=1; Path=/; SameSite=Lax${secure}`;
}

export function clearGuestCookie(): void {
  document.cookie = `${GUEST_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function isCoarsePointer(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(pointer: coarse)").matches;
}

function tabId(): string {
  try {
    let id = window.sessionStorage.getItem("fpl.guest.tabId");
    if (!id) {
      id = Math.random().toString(36).slice(2, 10);
      window.sessionStorage.setItem("fpl.guest.tabId", id);
    }
    return id;
  } catch {
    return "tab";
  }
}

function beat(id: string): void {
  try {
    window.localStorage.setItem(TAB_PREFIX + id, String(Date.now()));
  } catch {
    /* no storage: every close counts as the last tab */
  }
}

function forget(id: string): void {
  try {
    window.localStorage.removeItem(TAB_PREFIX + id);
  } catch {
    /* ignore */
  }
}

/** Another tab of this browser beat within TAB_STALE_MS (a crashed tab's stale beat does not count). */
export function otherTabAlive(id: string): boolean {
  try {
    const now = Date.now();
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (!k || !k.startsWith(TAB_PREFIX) || k === TAB_PREFIX + id) continue;
      const ts = Number(window.localStorage.getItem(k) ?? 0);
      if (now - ts < TAB_STALE_MS) return true;
      window.localStorage.removeItem(k);
    }
  } catch {
    /* ignore */
  }
  return false;
}

export type GuestWarning = { secondsLeft: number } | null;

/** The guest session's client logic for a page that knows the signed-in user (`me`). Returns the idle warning (null when
 *  none) and `stay` (the "I'm here" button) / `end` ("End guest session": deletes now, signs out, goes to /login). */
export function useGuestSession(me: Me | null): { warning: GuestWarning; stay: () => void; end: () => Promise<void> } {
  const { getToken } = useAuth();
  const isGuest = !!me?.is_guest;
  const idleMs = (me?.guest?.idle_minutes ?? 30) * 60_000;
  const [warning, setWarning] = useState<GuestWarning>(null);
  const lastActivity = useRef(0); // set when the effect starts (no impure call during render)
  const lastPing = useRef(0);
  const ending = useRef(false);

  // Leaving is a FULL navigation to the login note, never Clerk's signOut: once the Clerk user is gone, clerk-js retries its
  // token refresh with backoff for a long time (measured: 404s every ~2 s, the session still "signed in" after 100 s) and
  // signOut hangs with it; a fresh page load re-reads /v1/client, finds no session and is cleanly signed out. The cookie goes
  // first, so the login page shows the guest note.
  const leaveToLogin = useCallback(async () => {
    clearGuestCookie();
    window.location.assign(loginGuestEndedUrl());
  }, []);
  const end = useCallback(async () => {
    if (ending.current) return;
    ending.current = true;
    try {
      await api.deleteAccount(getToken);
    } catch {
      /* already gone (the reaper got there first) or offline: the sign-out below still ends it here */
    }
    await leaveToLogin();
  }, [getToken, leaveToLogin]);

  // a ping answered 401 (no session) or 503 (the row and the Clerk user are gone, the token not yet expired) means the server
  // already ended this guest (the reaper, the switch): go to the login note at once
  const endedElsewhere = useCallback(async () => {
    if (ending.current) return;
    ending.current = true;
    await leaveToLogin();
  }, [leaveToLogin]);
  // the ping fetches with its own bounded token wait: no token within TOKEN_WAIT_MS (clerk-js stuck refreshing a session the
  // server already ended) counts as "the session is over", like a 401 / 503 from the API
  const ping = useCallback(() => {
    lastPing.current = Date.now();
    void (async () => {
      const token = await Promise.race([getToken().catch(() => null), new Promise<null>((r) => window.setTimeout(() => r(null), TOKEN_WAIT_MS))]);
      if (!token) return void endedElsewhere();
      try {
        const res = await fetch(`${api.base}/me/ping`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (res.status === 401 || res.status === 503) void endedElsewhere();
      } catch {
        /* offline: the next ping tries again */
      }
    })();
  }, [getToken, endedElsewhere]);

  const stay = useCallback(() => {
    lastActivity.current = Date.now();
    setWarning(null);
    ping();
  }, [ping]);

  useEffect(() => {
    if (!isGuest) return;
    // a guest without the browser-session cookie: the browser was closed and reopened -> the session is over
    if (!hasGuestCookie()) {
      void end();
      return;
    }
    lastActivity.current = Date.now();
    const id = tabId();
    beat(id);
    ping();
    const beatTimer = window.setInterval(() => beat(id), TAB_BEAT_MS);
    const onActivity = () => {
      lastActivity.current = Date.now();
      if (Date.now() - lastPing.current >= PING_EVERY_MS) ping();
    };
    for (const ev of ACTIVITY_EVENTS) window.addEventListener(ev, onActivity, { passive: true, capture: true });
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        beat(id);
        ping();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    const coarse = isCoarsePointer();
    const onHide = () => {
      forget(id);
      if (coarse) return; // a phone: backgrounding is not closing (checkpoint Q1)
      if (otherTabAlive(id)) return;
      void (async () => {
        const token = await getToken().catch(() => null);
        if (!token) return;
        fetch(`${api.base}/me/leave`, { method: "POST", keepalive: true, headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined);
      })();
    };
    window.addEventListener("pagehide", onHide);
    const tick = window.setInterval(() => {
      const idle = Date.now() - lastActivity.current;
      if (idle >= idleMs) {
        setWarning(null);
        void end();
      } else if (idle >= idleMs - WARN_BEFORE_MS) {
        setWarning({ secondsLeft: Math.max(0, Math.ceil((idleMs - idle) / 1000)) });
      } else {
        setWarning((w) => (w ? null : w));
      }
    }, 1000);
    return () => {
      window.clearInterval(beatTimer);
      window.clearInterval(tick);
      for (const ev of ACTIVITY_EVENTS) window.removeEventListener(ev, onActivity, { capture: true } as EventListenerOptions);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pagehide", onHide);
    };
  }, [isGuest, idleMs, end, ping, getToken]);

  return { warning: isGuest ? warning : null, stay, end };
}
