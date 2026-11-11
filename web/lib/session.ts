"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { loginSignedOutUrl } from "./redirects";

export { safeRedirect, loginUrlFor, loginSignedOutUrl, SIGNED_OUT } from "./redirects";

/** Prompt W7b (F2), the client side: where the app sends a visitor whose session is gone (see lib/redirects.ts). */

export function currentPath(): string {
  if (typeof window === "undefined") return "/home";
  return `${window.location.pathname}${window.location.search}`;
}

export function loginSignedOut(router: { replace: (url: string) => void }): void {
  router.replace(loginSignedOutUrl(currentPath()));
}

/** A private page: once Clerk has loaded and says signed out (the session revoked, expired or ended elsewhere), go to
 *  /login with the reason and the way back. */
export function useSignedOutRedirect(): void {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();
  useEffect(() => {
    if (isLoaded && !isSignedIn) router.replace(loginSignedOutUrl(currentPath()));
  }, [isLoaded, isSignedIn, router]);
}
