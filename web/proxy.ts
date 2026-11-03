/**
 * Request proxy (Next.js 16's name for middleware), Prompt W1 (2026-11-02).
 *
 * 1. Site password (optional, OFF by default). When SITE_PASSWORD is set, every request -- pages AND static files, so
 *    the player photos are covered too -- must carry HTTP Basic credentials whose password matches (any user name).
 *    Unset -> this block does nothing. It is a class-use gate for a non-commercial project, not account security:
 *    accounts are Clerk's.
 * 2. Clerk. clerkMiddleware() reads the session for page and API requests (Clerk's own matcher, below); it is skipped
 *    for static files so the dev-instance handshake never runs on an image request.
 */
import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

const withClerk = clerkMiddleware();

// Clerk's documented matcher, as a regex: Next internals and static files are not Clerk's business.
const STATIC_FILE =
  /^\/(?:_next\/|.*\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest|mp3|m4a)$)/i;

function constantTimeEqual(a: string, b: string): boolean {
  // same length or not, every character is compared, so the time does not say where the mismatch is
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

function sitePasswordOk(req: NextRequest, password: string): boolean {
  const header = req.headers.get("authorization") ?? "";
  if (!header.startsWith("Basic ")) return false;
  let decoded = "";
  try {
    decoded = atob(header.slice(6).trim());
  } catch {
    return false;
  }
  const colon = decoded.indexOf(":");
  const supplied = colon >= 0 ? decoded.slice(colon + 1) : "";
  return constantTimeEqual(supplied, password);
}

export default function proxy(req: NextRequest, ev: NextFetchEvent) {
  const password = process.env.SITE_PASSWORD;
  if (password && !sitePasswordOk(req, password)) {
    return new NextResponse("Authentication required", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="FPL Copilot", charset="UTF-8"', "Cache-Control": "no-store" },
    });
  }
  if (STATIC_FILE.test(req.nextUrl.pathname)) {
    return NextResponse.next();
  }
  return withClerk(req, ev);
}

export const config = {
  // everything except Next's own static chunks, so the site password covers the media; Clerk filters further above
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
