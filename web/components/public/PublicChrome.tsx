"use client";

import { GuestSession } from "@/components/guest/GuestSession";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { AccountMenu, Logo } from "@/components/home/HomeHeader";
import { MusicButton } from "@/components/music/MusicButton";

/** The About / Privacy chrome (Prompt W5): the header switches on the Clerk session -- "Sign in" (cyan) when signed out,
 *  "← Home" + the ONE account menu when signed in (the phone shows an icon-only 44px Home button); the footer names the
 *  page; the backdrop is the glow, the pitch grid and the page's photo (fixed from 1024px, absolute below; aria-hidden,
 *  pointer-events none). */

export function PublicHeader() {
  const { isLoaded, isSignedIn } = useAuth();
  return (
    <header className="pp-hdr" data-testid="public-header" data-signed-in={isLoaded ? isSignedIn : "loading"}>
      <Logo />
      <div className="pp-grow" />
      {isLoaded && isSignedIn && (
        <Link href="/home" className="pp-home" aria-label="Home" data-testid="header-home">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M19 12H5M11 18l-6-6 6-6" />
          </svg>
          <span>Home</span>
        </Link>
      )}
      <MusicButton />
      {isLoaded && isSignedIn && <GuestSession />}
      {!isLoaded ? (
        <span className="pp-hdr-slot" aria-hidden="true" />
      ) : isSignedIn ? (
        <AccountMenu />
      ) : (
        <Link href="/login" prefetch={false} className="pp-signin" data-testid="header-sign-in">
          Sign in
        </Link>
      )}
    </header>
  );
}

export function PublicFooter({ page }: { page: "about" | "privacy" }) {
  return (
    <footer className="pp-foot" data-testid="public-footer">
      <span className="pp-foot-lbl">FPL COPILOT · INDEPENDENT PROJECT</span>
      <nav aria-label="Legal">
        <Link href="/privacy" aria-current={page === "privacy" ? "page" : undefined}>
          Privacy
        </Link>
        <Link href="/about" aria-current={page === "about" ? "page" : undefined}>
          About
        </Link>
      </nav>
    </footer>
  );
}

export function Backdrop({ page }: { page: "about" | "privacy" }) {
  return (
    <>
      <div aria-hidden="true" className="pp-glow" />
      <div aria-hidden="true" className="pp-grid" />
      {/* eslint-disable-next-line @next/next/no-img-element -- the design's background photo, masked; decorative */}
      <img src={`/images/${page}-bg.webp`} alt="" aria-hidden="true" className={`pp-photo ${page}`} data-testid="bg-photo" />
    </>
  );
}

export const Arrow = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
