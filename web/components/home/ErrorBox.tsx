"use client";

import type { ApiError } from "@/lib/api";

/** The error state of one backend call: what failed, why (short), and Retry. */
export function ErrorBox({ what, error, onRetry, className = "" }: { what: string; error: ApiError; onRetry: () => void; className?: string }) {
  const why =
    error.status === 0
      ? "the API could not be reached"
      : error.status === 401
        ? "your session was not accepted"
        : error.status === 429
          ? "too many requests; wait a moment"
          : `the API answered ${error.status}`;
  return (
    <section className={`hm-glass hm-err ${className}`.trim()} role="alert" data-testid={`error-${what.replace(/\s+/g, "-")}`}>
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <p>Couldn’t load {what}.</p>
      <small>{why}</small>
      <button type="button" className="hm-btn-o" onClick={onRetry}>
        Retry
      </button>
    </section>
  );
}
