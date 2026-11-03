"use client";

import { forwardRef, type FormEvent } from "react";

/** The sign-in card, default state (Part 2: layout and final copy; Part 3 wires Clerk and the other states). */
export const SignInCard = forwardRef<HTMLElement, object>(function SignInCard(_props, ref) {
  const onSubmit = (e: FormEvent) => e.preventDefault();
  return (
    <section ref={ref} className="card rise" aria-labelledby="c-title" tabIndex={-1} data-testid="sign-in-card">
      <span className="bracket b-tl" aria-hidden="true" />
      <span className="bracket b-tr" aria-hidden="true" />
      <span className="bracket b-bl" aria-hidden="true" />
      <span className="bracket b-br" aria-hidden="true" />
      <div className="card-head is-default">
        <span className="card-eyebrow mono">SIGN IN · SIGN UP</span>
        <h2 id="c-title">Step into the dugout</h2>
        <p className="card-body">No password needed. New here? We’ll set up your account as you sign in.</p>
      </div>
      <button type="button" className="gbtn" data-testid="google">
        {/* eslint-disable-next-line @next/next/no-img-element -- Google's own "G" asset, used as supplied */}
        <img src="/google-g.svg" alt="" width={20} height={20} />
        Continue with Google
      </button>
      <div className="divider" aria-hidden="true">
        <i />
        <span className="mono">OR</span>
        <i />
      </div>
      <form onSubmit={onSubmit} className="field" noValidate>
        <label htmlFor="c-email">Email</label>
        <input id="c-email" className="input" type="email" name="email" autoComplete="email" placeholder="you@example.com" />
        <button type="submit" className="cta" style={{ marginTop: 12 }} data-testid="send-code">
          Email me a 6-digit code
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      </form>
      <p className="fine is-default">We’ll email you a code to confirm it’s you.</p>
    </section>
  );
});
