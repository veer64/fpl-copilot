"use client";

import { forwardRef, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useClerk, useSignIn, useSignUp } from "@clerk/nextjs";
import { isClerkAPIResponseError } from "@clerk/nextjs/errors";
import { REGEXP_ONLY_DIGITS } from "input-otp";
import { toast } from "sonner";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";

/** The sign-in card (Prompt W1 Part 3). Clerk Core 3 hooks, our own UI:
 *  - email -> `signIn.create({identifier})` -> `signIn.emailCode.sendCode()`; an unknown address falls back to
 *    `signUp.create({emailAddress})` -> `signUp.verifications.sendEmailCode()` (form_identifier_not_found);
 *  - code (InputOTP, auto-submits on the 6th digit) -> `verifyCode` -> `finalize({navigate})` -> /teams;
 *  - Google -> `signIn.sso()` -> /sso-callback -> /teams.
 *  States per BRIEF.md: loading, code sent, wrong, expired, resend (30 s cooldown + toast), too many attempts, generic
 *  error. Errors are announced (role="alert") and linked to their field (aria-describedby). */

type Step = "email" | "code";
type Busy = null | "sending" | "verifying" | "google" | "resending";
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

  const goToApp = ({ decorateUrl }: { decorateUrl: (url: string) => string }) => {
    const url = decorateUrl("/teams");
    if (url.startsWith("http")) window.location.href = url;
    else router.push(url);
  };

  // --- step 1: send the code -------------------------------------------------------------------------------------------
  const failSend = (err: unknown) => {
    const c = apiCode(err);
    if (c === "session_exists") return router.push("/teams");
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
      setStep("code");
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
    setStep("email");
    setCode("");
    setCodeError(null);
    setCooldown(0);
    await Promise.allSettled([signIn.reset(), signUp.reset()]);
    window.requestAnimationFrame(() => emailRef.current?.focus());
  };

  const tryAgain = () => {
    setFatal(false);
    setBusy(null);
    if (step === "code") setCodeError(null);
    window.requestAnimationFrame(() => (step === "code" ? otpRef.current : emailRef.current)?.focus());
  };

  // --- Google -----------------------------------------------------------------------------------------------------------
  const google = async () => {
    setBusy("google");
    try {
      const { error } = await signIn.sso({ strategy: "oauth_google", redirectCallbackUrl: "/sso-callback", redirectUrl: "/teams" });
      if (!error) return; // the browser is leaving for Google: keep "Connecting…"
      if (apiCode(error) === "session_exists") return router.push("/teams");
      console.error("[sign-in] Google failed", error);
      setFatal(true);
    } catch (err) {
      console.error("[sign-in] Google failed", err);
      setFatal(true);
    }
    setBusy(null);
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
        </>
      )}
    </section>
  );
});
