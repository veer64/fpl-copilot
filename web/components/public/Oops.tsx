"use client";

import Link from "next/link";
import { MusicButton } from "@/components/music/MusicButton";

/** Prompt W7b (F4): the branded "page doesn't exist" (app/not-found.tsx) and "something went wrong" (app/error.tsx) screens --
 *  the site's dark page, the logo, a glass card with brackets, Home / Sign in links (no account data: nothing here reads the
 *  session), the music button. */
export function Oops({ kind, onRetry }: { kind: "404" | "error"; onRetry?: () => void }) {
  const notFound = kind === "404";
  return (
    <div className="pp oops" data-testid={notFound ? "not-found" : "error-page"}>
      <div aria-hidden="true" className="pp-glow" />
      <div aria-hidden="true" className="pp-grid" />
      <header className="pp-hdr" data-testid="public-header">
        <Link href="/home" className="hm-brand" aria-label="FPL Copilot home">
          {/* eslint-disable-next-line @next/next/no-img-element -- the 28px logo, as everywhere */}
          <img src="/logo.svg" alt="" width={28} height={28} />
          <span>FPL Copilot</span>
        </Link>
        <div className="pp-grow" />
        <MusicButton />
      </header>
      <main className="oops-main">
        <section className="hm-glass oops-card" aria-labelledby="oops-title">
          <span className="hm-br hm-tl" aria-hidden="true" />
          <span className="hm-br hm-brr" aria-hidden="true" />
          <span className="pp-eyebrow">{notFound ? "404" : "ERROR"}</span>
          <h1 id="oops-title">{notFound ? "This page doesn’t exist." : "Something went wrong."}</h1>
          <p className="pp-p">{notFound ? "The link may be old, or the address has a typo." : "The page hit an error it could not recover from. Try again, or go back home."}</p>
          <div className="oops-actions">
            {!notFound && onRetry && (
              <button type="button" className="hm-btn-p oops-btn" onClick={onRetry} data-testid="oops-retry">
                Try again
              </button>
            )}
            <Link href="/home" className={notFound ? "hm-btn-p oops-btn" : "hm-btn-s oops-btn"} data-testid="oops-home">
              Home
            </Link>
            {notFound && (
              <Link href="/login" prefetch={false} className="hm-btn-s oops-btn" data-testid="oops-sign-in">
                Sign in
              </Link>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
