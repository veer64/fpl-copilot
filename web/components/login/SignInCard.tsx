"use client";

import { forwardRef, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { safeRedirect } from "@/lib/redirects";
import { useClerk, useSignIn, useSignUp } from "@clerk/nextjs";
import { guestStart, guestStatus, type GuestStartError } from "@/lib/api";
import { setGuestCookie } from "@/lib/guest";
import { isClerkAPIResponseError } from "@clerk/nextjs/errors";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { toast } from "sonner";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";

/** The sign-in card (Prompt W1 Part 3). Clerk Core 3 hooks, our own UI:
 *  - email -> `signIn.create({identifier})` -> `signIn.emailCode.sendCode()`; an unknown address falls back to
 *    `signUp.create({emailAddress})` -> `signUp.verifications.sendEmailCode()` (form_identifier_not_found);
 *  - code (InputOTP, auto-submits on the 6th digit) -> `verifyCode` -> `finalize({navigate})` -> /home (Prompt W3: was /teams);
 *  - Google -> `signIn.sso()` -> /sso-callback -> /home.
 *  States per BRIEF.md: loading, code sent, wrong, expired, resend (30 s cooldown + toast), too many attempts, generic
 *  error. Errors are announced (role="alert") and linked to their field (aria-describedby). */

type Step = "email" | "code";
type Busy = null | "sending" | "verifying" | "google" | "resending" | "guest";

// Prompt W9: the guest option's wording (checkpoint 4; the chat-side texts come from the server)
const GUEST_UNAVAILABLE = "Guest mode is unavailable";
const GUEST_IP_LIMIT = "Guest limit reached for today on this network — sign in with Google or email to keep going";
const GUEST_BUDGET_FULL = "Guest mode is full for today — sign in to continue";
const GUEST_BUSY = "Guest mode is busy — try again in a few minutes, or sign in."; // Prompt S1: the global start limit
const GUEST_FAILED = "Couldn’t start a guest session — try again, or sign in.";
type Flow = "signin" | "signup";
type CodeError = { kind: "wrong" | "expired" | "too_many" | "generic"; text: string };

export const COPY = {
  wrong: "That code isn’t right. Check your email and try again.",
  expired: "That code has expired.",
  tooMany: "Too many attempts. Wait a minute and try again.",
  generic: "Something went wrong on our side. Please try again.",
  badEmail: "Enter a valid email address.",
  newCode: "New code sent.",
} as const;

const RESEND_SECONDS = 30;
const EMAIL_RX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/** Continue with Google must leave the page within this time, or the card shows the generic error (never an endless
 *  spinner): clerk-js retries a failed Frontend API request with backoff, so `signIn.sso()` can stay pending for a long
 *  time when the request is blocked or the network is down (seen 2 Nov 2026). */
const SSO_TIMEOUT_MS = 12_000;

function apiCode(err: unknown): string | null {
  return isClerkAPIResponseError(err) ? (err.errors[0]?.code ?? null) : null;
}

/** Clerk's verification error codes -> the BRIEF's states. */
function codeErrorFor(code: string | null): CodeError {
  switch (code) {
    case "form_code_incorrect":
      return { kind: "wrong", text: COPY.wrong };
    case "verification_expired":
      return { kind: "expired", text: COPY.expired };
    case "verification_failed":
    case "too_many_requests":
      return { kind: "too_many", text: COPY.tooMany };
    default:
      return { kind: "generic", text: COPY.generic };
  }
}

const fmt = (s: number) => `0:${String(s).padStart(2, "0")}`;

const Spinner = () => <span className="spin" aria-hidden="true" />;

export const SignInCard = forwardRef<HTMLElement, object>(function SignInCard(_props, ref) {
  const router = useRouter();
  const params = useSearchParams();
  const clerk = useClerk();
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();

  const [step, setStep] = useState<Step>("email");
  const [flow, setFlow] = useState<Flow>("signin");
  const [busy, setBusy] = useState<Busy>(null);
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<CodeError | null>(null);
  const [fatal, setFatal] = useState<boolean>(() => params.get("sso") === "incomplete");
  const [cooldown, setCooldown] = useState(0);
  // Prompt W9: the kill switch read once (GET /guest/status); unreachable -> the button stays and the click reports the error
  const [guestMode, setGuestMode] = useState<"loading" | "on" | "off">("loading");
  const [guestIdle, setGuestIdle] = useState(30);
  const [guestError, setGuestError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    guestStatus()
      .then((s) => {
        if (!alive) return;
        setGuestMode(s.enabled ? "on" : "off");
        setGuestIdle(s.idle_minutes);
      })
      .catch(() => alive && setGuestMode("on"));
    return () => {
      alive = false;
    };
  }, []);
  const emailRef = useRef<HTMLInputElement | null>(null);
  const otpRef = useRef<HTMLInputElement | null>(null);

  const ticking = cooldown > 0;
  useEffect(() => {
    if (!ticking) return;
    const t = window.setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => window.clearInterval(t);
  }, [ticking]);

  useEffect(() => {
    if (step === "code") otpRef.current?.focus();
  }, [step]);

  // the code input sits in a fieldset that is disabled while busy, so a refocus after a wrong code or a resend has to wait
  // for the commit that re-enables it (a rAF could run before React's render and focus nothing)
  const refocusOtp = useRef(false);
  useEffect(() => {
    if (busy || !refocusOtp.current) return;
    refocusOtp.current = false;
    otpRef.current?.focus();
  }, [busy]);

  // W7b (F2): back to the page the visitor came from (?redirect_url, same-site relative paths only), else /home
  const returnTo = safeRedirect(params.get("redirect_url")) ?? "/home";
  const goToApp = ({ decorateUrl }: { decorateUrl: (url: string) => string }) => {
    const url = decorateUrl(returnTo);
    if (url.startsWith("http")) window.location.href = url;
    else router.push(url);
  };

  // W7b (F11): the code step is a history entry, so Back returns to the email step instead of leaving the page
  const codeEntry = useRef(false);
  useEffect(() => {
    const onPop = () => {
      if (codeEntry.current) {
        codeEntry.current = false;
        setStep("email");
        setCode("");
        setCodeError(null);
        window.requestAnimationFrame(() => emailRef.current?.focus());
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const enterCodeStep = () => {
    if (!codeEntry.current) {
      window.history.pushState({ step: "code" }, "", window.location.href);
      codeEntry.current = true;
    }
    setStep("code");
  };

  // --- step 1: send the code -------------------------------------------------------------------------------------------
  const failSend = (err: unknown) => {
    const c = apiCode(err);
    if (c === "session_exists") return router.push("/home");
    if (c === "form_param_format_invalid" || c === "form_identifier_invalid" || c === "form_param_nil") return setEmailError(COPY.badEmail);
    if (c === "too_many_requests") return setEmailError(COPY.tooMany);
    console.error("[sign-in] sending the code failed", err);
    setFatal(true);
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const address = email.trim();
    setEmailError(null);
    if (!EMAIL_RX.test(address)) {
      setEmailError(COPY.badEmail);
      emailRef.current?.focus();
      return;
    }
    setBusy("sending");
    try {
      let nextFlow: Flow = "signin";
      const { error } = await signIn.create({ identifier: address });
      if (error) {
        if (apiCode(error) !== "form_identifier_not_found") return failSend(error);
        // no account for this address: the same flow signs the visitor up
        nextFlow = "signup";
        const created = await signUp.create({ emailAddress: address });
        if (created.error) return failSend(created.error);
        const sent = await signUp.verifications.sendEmailCode();
        if (sent.error) return failSend(sent.error);
      } else {
        const sent = await signIn.emailCode.sendCode();
        if (sent.error) return failSend(sent.error);
      }
      setFlow(nextFlow);
      setCode("");
      setCodeError(null);
      setCooldown(RESEND_SECONDS);
      enterCodeStep();
    } catch (err) {
      failSend(err);
    } finally {
      setBusy(null);
    }
  };

  // --- step 2: verify ---------------------------------------------------------------------------------------------------
  const failVerify = (err: unknown) => {
    setCodeError(codeErrorFor(apiCode(err)));
    setCode("");
    refocusOtp.current = true;
  };

  const verify = async (value: string) => {
    if (busy) return;
    setBusy("verifying");
    setCodeError(null);
    try {
      if (flow === "signin") {
        const { error } = await signIn.emailCode.verifyCode({ code: value });
        if (error) return failVerify(error);
        if (signIn.status === "complete") return void (await signIn.finalize({ navigate: goToApp }));
        console.error("[sign-in] not complete after the code:", signIn.status);
        return failVerify(null);
      }
      const { error } = await signUp.verifications.verifyEmailCode({ code: value });
      if (error) return failVerify(error);
      if (signUp.status === "complete") return void (await signUp.finalize({ navigate: goToApp }));
      if (signUp.missingFields.includes("password")) {
        console.warn("[sign-up] the Clerk instance still requires a password; turn it off in the dashboard (BRIEF: passwords OFF)");
      }
      console.error("[sign-up] not complete after the code:", signUp.status, signUp.missingFields);
      return failVerify(null);
    } catch (err) {
      failVerify(err);
    } finally {
      setBusy(null);
    }
  };

  const resend = async (force = false) => {
    if ((cooldown > 0 && !force) || busy) return;
    setBusy("resending");
    setCodeError(null);
    setCode("");
    try {
      const { error } = flow === "signin" ? await signIn.emailCode.sendCode() : await signUp.verifications.sendEmailCode();
      if (error) {
        const c = apiCode(error);
        setCodeError(c === "too_many_requests" ? { kind: "too_many", text: COPY.tooMany } : { kind: "generic", text: COPY.generic });
        return;
      }
      setCooldown(RESEND_SECONDS);
      toast.success(COPY.newCode);
    } catch (err) {
      console.error("[sign-in] resend failed", err);
      setCodeError({ kind: "generic", text: COPY.generic });
    } finally {
      refocusOtp.current = true;
      setBusy(null);
    }
  };

  const differentEmail = async () => {
    if (codeEntry.current) {
      codeEntry.current = false;
      window.history.back(); // drops the code-step entry; popstate has nothing left to do
    }
    setStep("email");
    setCode("");
    setCodeError(null);
    setCooldown(0);
    await Promise.allSettled([signIn.reset(), signUp.reset()]);
    window.requestAnimationFrame(() => emailRef.current?.focus());
  };

  const tryAgain = () => {
    clearDeadline();
    setFatal(false);
    setBusy(null);
    if (step === "code") setCodeError(null);
    window.requestAnimationFrame(() => (step === "code" ? otpRef.current : emailRef.current)?.focus());
  };

  // --- Prompt W9: Continue as guest -- POST /guest/start -> a one-time Clerk sign-in token -> signIn.ticket -> the app -----
  const guest = async () => {
    setGuestError(null);
    setBusy("guest");
    try {
      const { ticket } = await guestStart();
      const { error } = await signIn.ticket({ ticket });
      if (error) throw error;
      if (signIn.status !== "complete") throw new Error(`guest sign-in needs a step this page does not handle: ${signIn.status}`);
      setGuestCookie();
      return void (await signIn.finalize({ navigate: goToApp }));
    } catch (err) {
      const code = (err as Partial<GuestStartError>)?.code;
      if (code === "guest_off") setGuestMode("off");
      setGuestError(
        code === "guest_off"
          ? GUEST_UNAVAILABLE
          : code === "guest_ip_limit"
            ? GUEST_IP_LIMIT
            : code === "guest_budget"
              ? GUEST_BUDGET_FULL
              : code === "guest_busy"
                ? GUEST_BUSY
                : GUEST_FAILED,
      );
      console.error("[guest] start failed", err);
    } finally {
      setBusy(null);
    }
  };

  // --- Google -----------------------------------------------------------------------------------------------------------
  // One deadline covers everything after the click: a request that fails (clerk-js keeps retrying, so sso() stays
  // pending), one that hangs, and a resolution that does not navigate. A real redirect unloads the page, timer and all.
  const ssoDeadline = useRef<number | null>(null);
  const clearDeadline = () => {
    if (ssoDeadline.current !== null) window.clearTimeout(ssoDeadline.current);
    ssoDeadline.current = null;
  };
  useEffect(() => clearDeadline, []);
  // W10: back from Google (or any page restored from the back-forward cache): the pending button is given back and the
  // redirect deadline, frozen with the page, can no longer fire "Google failed" afterwards
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (!e.persisted) return;
      if (ssoDeadline.current !== null) window.clearTimeout(ssoDeadline.current);
      ssoDeadline.current = null;
      setBusy(null);
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  const googleFailed = (why: unknown) => {
    clearDeadline();
    console.error("[sign-in] Google failed", why);
    setFatal(true);
    setBusy(null);
  };

  const google = async () => {
    setBusy("google");
    clearDeadline();
    ssoDeadline.current = window.setTimeout(() => googleFailed(`no redirect to Google within ${SSO_TIMEOUT_MS / 1000} s`), SSO_TIMEOUT_MS);
    try {
      const { error } = await signIn.sso({ strategy: "oauth_google", redirectCallbackUrl: "/sso-callback", redirectUrl: returnTo });
      if (error) {
        if (apiCode(error) === "session_exists") return router.push("/home");
        return googleFailed(error);
      }
      // no error: the browser should now be leaving for Google. Per the docs, a sign-in that instead needs another step
      // (second factor, device trust, a Protect challenge) is one this card does not handle -- say so instead of spinning.
      if (signIn.status === "needs_second_factor" || signIn.status === "needs_client_trust" || signIn.status === "needs_protect_check") {
        return googleFailed(`sign-in needs a step this page does not handle: ${signIn.status}`);
      }
      // otherwise keep "Connecting to Google…" until the page unloads, bounded by the deadline above
    } catch (err) {
      googleFailed(err);
    }
  };

  const disabled = !!busy || !clerk.loaded;
  const isCode = step === "code";

  return (
    <section
      ref={ref}
      className={`card rise${isCode || fatal ? " is-state" : ""}`}
      aria-labelledby="c-title"
      aria-busy={!!busy}
      tabIndex={-1}
      data-testid="sign-in-card"
      data-step={fatal ? "error" : step}
      data-flow={flow}
    >
      <span className="bracket b-tl" aria-hidden="true" />
      <span className="bracket b-tr" aria-hidden="true" />
      <span className="bracket b-bl" aria-hidden="true" />
      <span className="bracket b-br" aria-hidden="true" />
      {/* W7b (F1): Clerk's custom-flow CAPTCHA mount point -- in the DOM before any signUp.create() or signIn.sso() call
          (both steps and the Google button can start a sign-up); Clerk's smart CAPTCHA renders here on production */}
      <div id="clerk-captcha" data-testid="clerk-captcha" data-cl-theme="dark" data-cl-size="flexible" />

      {fatal ? (
        <>
          <div className="card-head">
            <span className="card-eyebrow mono">SIGN IN · SIGN UP</span>
            <h2 id="c-title">Something went wrong</h2>
            <p className="err" role="alert" data-testid="fatal-error">
              {COPY.generic}
            </p>
          </div>
          <button type="button" className="cta" onClick={tryAgain} data-testid="try-again">
            Try again
          </button>
        </>
      ) : isCode ? (
        <>
          <div className="card-head">
            <span className="card-eyebrow mono">{flow === "signup" ? "NEW ACCOUNT · ONE STEP" : "SIGN IN · SIGN UP"}</span>
            <h2 id="c-title" data-testid="code-sent-title">
              Check your email
            </h2>
            <p className="card-body">
              We sent a 6-digit code to <strong data-testid="code-sent-email">{email.trim()}</strong>.
            </p>
          </div>
          <fieldset disabled={disabled} className="otp-row" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            <label htmlFor="c-code" className="field-label">
              6-digit code
            </label>
            <InputOTP
              id="c-code"
              ref={otpRef}
              maxLength={6}
              value={code}
              onChange={setCode}
              onComplete={verify}
              pattern={REGEXP_ONLY_DIGITS}
              inputMode="numeric"
              autoComplete="one-time-code"
              containerClassName="otp"
              data-testid="otp"
              aria-describedby={codeError ? "c-code-help c-code-error" : "c-code-help"}
              aria-invalid={codeError ? true : undefined}
            >
              <InputOTPGroup className="otp-group">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <InputOTPSlot key={i} index={i} className="otp-slot" />
                ))}
              </InputOTPGroup>
            </InputOTP>
            <p id="c-code-help" className="fine" aria-live="polite">
              {busy === "verifying" ? (
                <>
                  <Spinner /> Verifying…
                </>
              ) : busy === "resending" ? (
                <>
                  <Spinner /> Sending code…
                </>
              ) : (
                "Type or paste the code; it submits itself."
              )}
            </p>
            {codeError && (
              <p id="c-code-error" className="err" role="alert" data-testid="code-error" data-kind={codeError.kind}>
                {codeError.text}
              </p>
            )}
          </fieldset>
          <div className="otp-actions">
            {codeError?.kind === "expired" ? (
              <button type="button" className="cta" onClick={() => resend(true)} disabled={disabled} data-testid="send-new-code">
                Send a new code
              </button>
            ) : (
              <p className="fine">
                Didn’t get it?{" "}
                {cooldown > 0 ? (
                  <span data-testid="resend-cooldown">Resend in {fmt(cooldown)}</span>
                ) : (
                  <button type="button" className="linkish" onClick={() => resend()} disabled={disabled} data-testid="resend">
                    Resend code
                  </button>
                )}
              </p>
            )}
            <button type="button" className="linkish" onClick={differentEmail} disabled={!!busy} data-testid="different-email">
              Use a different email
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="card-head is-default">
            <span className="card-eyebrow mono">SIGN IN · SIGN UP</span>
            <h2 id="c-title">Step into the dugout</h2>
            <p className="card-body">No password needed. New here? We’ll set up your account as you sign in.</p>
          </div>
          <button type="button" className="gbtn" onClick={google} disabled={disabled} data-testid="google">
            {busy === "google" ? (
              <>
                <Spinner /> Connecting to Google…
              </>
            ) : (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element -- Google's own "G" asset, used as supplied */}
                <img src="/google-g.svg" alt="" width={20} height={20} />
                Continue with Google
              </>
            )}
          </button>
          <div className="divider" aria-hidden="true">
            <i />
            <span className="mono">OR</span>
            <i />
          </div>
          <form onSubmit={send} noValidate>
            <fieldset disabled={disabled} className="field" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
              <label htmlFor="c-email">Email</label>
              <input
                id="c-email"
                ref={emailRef}
                className="input"
                type="email"
                name="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-describedby={emailError ? "c-email-error" : undefined}
                aria-invalid={emailError ? true : undefined}
              />
              {emailError && (
                <p id="c-email-error" className="err" role="alert" data-testid="email-error">
                  {emailError}
                </p>
              )}
              <button type="submit" className="cta" style={{ marginTop: 12 }} data-testid="send-code">
                {busy === "sending" ? (
                  <>
                    <Spinner /> Sending code…
                  </>
                ) : (
                  <>
                    Email me a 6-digit code
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M5 12h14M13 6l6 6-6 6" />
                    </svg>
                  </>
                )}
              </button>
            </fieldset>
          </form>
          <p className="fine is-default">We’ll email you a code to confirm it’s you.</p>
          <div className="divider" aria-hidden="true">
            <i />
            <span className="mono">OR</span>
            <i />
          </div>
          <button type="button" className="gbtn guest" onClick={guest} disabled={disabled || guestMode === "off"} data-testid="continue-as-guest" data-guest-mode={guestMode}>
            {busy === "guest" ? (
              <>
                <Spinner /> Starting a guest session…
              </>
            ) : guestMode === "off" ? (
              GUEST_UNAVAILABLE
            ) : (
              <>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="8" r="4" />
                  <path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" />
                </svg>
                Continue as guest
              </>
            )}
          </button>
          {guestError ? (
            <p className="err" role="alert" data-testid="guest-error">
              {guestError}
            </p>
          ) : (
            <p className="fine is-default" data-testid="guest-note">
              No sign-up. Deleted when you leave or after {guestIdle} minutes idle.
            </p>
          )}
        </>
      )}
    </section>
  );
});
