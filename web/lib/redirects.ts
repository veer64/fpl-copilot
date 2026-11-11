/** Prompt W7b (F2): the login return URL, server- and client-safe (no React, no "use client").
 *  - A private page opened signed out redirects to `/login?redirect_url=<path+query>` (loginUrlFor); the card returns there
 *    after the sign-in (safeRedirect: same-site relative paths only -- "/..." but never "//...", nothing with a scheme or a
 *    backslash, never /login itself -- else /home, so no open redirect).
 *  - The app detecting a lost session (a 401, or Clerk saying signed out) goes to `/login?reason=signed_out&redirect_url=…`
 *    (loginSignedOutUrl): the login page shows "You were signed out — sign in to continue." and skips the intro. A normal
 *    Sign out carries no reason, so no note. */

export const SIGNED_OUT = "signed_out";

export function safeRedirect(value: string | null | undefined): string | null {
  if (!value) return null;
  let v = value;
  try {
    v = decodeURIComponent(value);
  } catch {
    v = value;
  }
  if (!v.startsWith("/") || v.startsWith("//") || v.startsWith("/\\") || /[\\\r\n]/.test(v) || /^\/[a-z]+:/i.test(v)) return null;
  if (v.startsWith("/login")) return null;
  return v;
}

/** The /login URL a server page redirects a signed-out visitor to. */
export function loginUrlFor(path: string): string {
  const safe = safeRedirect(path);
  return safe ? `/login?redirect_url=${encodeURIComponent(safe)}` : "/login";
}

/** The /login URL when the app itself found the session gone (a 401 from the API, or Clerk signed out). */
export function loginSignedOutUrl(path: string): string {
  const safe = safeRedirect(path);
  return `/login?reason=${SIGNED_OUT}${safe ? `&redirect_url=${encodeURIComponent(safe)}` : ""}`;
}
