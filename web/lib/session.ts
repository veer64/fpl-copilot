"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { loginGuestEndedUrl, loginSignedOutUrl } from "./redirects";
import { clearGuestCookie, hasGuestCookie } from "./guest";

export { safeRedirect, loginUrlFor, loginSignedOutUrl, loginGuestEndedUrl, SIGNED_OUT, GUEST_ENDED } from "./redirects";

/** Prompt W7b (F2), the client side: where the app sends a visitor whose session is gone (see lib/redirects.ts). */

export function currentPath(): string {
  if (typeof window === "undefined") return "/home";
  return `${window.location.pathname}${window.location.search}`;
}

/** W9: a lost session that still carries the fpl_guest cookie was a guest session (the reaper or the switch ended it on the
 *  server): the login page says so and the cookie goes; a person's lost session is the W7b note. */
function lostSessionUrl(): string {
  if (hasGuestCookie()) {
    clearGuestCookie();
    return loginGuestEndedUrl();
  }
  return loginSignedOutUrl(currentPath());
}

export function loginSignedOut(router: { replace: (url: string) => void }): void {
  router.replace(lostSessionUrl());
}

/** A private page: once Clerk has loaded and says signed out (the session revoked, expired or ended elsewhere), go to
 *  /login with the reason and the way back. */
export function useSignedOutRedirect(): void {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();
  useEffect(() => {
    if (isLoaded && !isSignedIn) router.replace(lostSessionUrl());
  }, [isLoaded, isSignedIn, router]);
}
