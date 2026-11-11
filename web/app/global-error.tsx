"use client";

import { useEffect } from "react";

/** Prompt W7b (F4): a crash in the root layout itself (no providers, no stylesheets left) still shows a branded page with
 *  Try again and Home. Inline styles on purpose: this screen must render with nothing else loaded. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("[global error]", error);
  }, [error]);
  const btn = { height: 44, padding: "0 18px", borderRadius: 12, fontWeight: 600, fontSize: 14, display: "inline-flex", alignItems: "center", textDecoration: "none", cursor: "pointer", fontFamily: "inherit" } as const;
  return (
    <html lang="en">
      <body style={{ margin: 0, minHeight: "100vh", background: "#04070C", color: "#E8F6FF", fontFamily: "system-ui, sans-serif", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
        <main style={{ width: "min(480px, 100%)", padding: 28, borderRadius: 16, background: "rgba(8,15,24,.9)", border: "1px solid rgba(59,232,255,.3)" }} data-testid="error-page">
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18, color: "#3BE8FF", fontWeight: 600 }}>
            {/* eslint-disable-next-line @next/next/no-img-element -- the logo */}
            <img src="/logo.svg" alt="" width={28} height={28} />
            <span style={{ color: "#E8F6FF" }}>FPL Copilot</span>
          </div>
          <h1 style={{ margin: 0, fontSize: 28, lineHeight: "34px", letterSpacing: "-.02em", color: "#F2FBFF" }}>Something went wrong.</h1>
          <p style={{ margin: "10px 0 20px", color: "#A9BACB", fontSize: 15, lineHeight: "22px" }}>The page hit an error it could not recover from. Try again, or go back home.</p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button type="button" onClick={reset} style={{ ...btn, border: 0, background: "#3BE8FF", color: "#021016" }} data-testid="oops-retry">
              Try again
            </button>
            <a href="/home" style={{ ...btn, border: "1px solid #2C4052", background: "rgba(255,255,255,.03)", color: "#E8F6FF" }} data-testid="oops-home">
              Home
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
