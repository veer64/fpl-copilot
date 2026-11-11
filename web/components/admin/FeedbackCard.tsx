"use client";

import type { AdminSummary } from "@/lib/api";
import { fmtUtc } from "./format";

/** Thumbs (Prompt W6): up / down totals (all time + last 7 days) and the 20 most recent thumbs-down answers -- when, who,
 *  the question, the first 300 characters of the answer and the Langfuse trace (a link when the backend knows the project,
 *  else the trace id alone). Admin-only, so the trace link is fine here. */
export function FeedbackCard({ feedback, langfuse }: { feedback: AdminSummary["feedback"]; langfuse: AdminSummary["langfuse"] }) {
  const f = feedback;
  return (
    <div className="ad-fb" data-testid="feedback">
      <dl className="ad-fb-totals">
        <div className="ad-fb-tot up" data-testid="thumbs-up">
          <dt>
            <ThumbUp /> Thumbs up
          </dt>
          <dd>
            <b data-testid="v-up_total" data-value={f.up_total}>
              {f.up_total}
            </b>
            <small>
              <span data-testid="v-up_7_days" data-value={f.up_7_days}>
                {f.up_7_days}
              </span>{" "}
              in the last 7 days
            </small>
          </dd>
        </div>
        <div className="ad-fb-tot down" data-testid="thumbs-down">
          <dt>
            <ThumbDown /> Thumbs down
          </dt>
          <dd>
            <b data-testid="v-down_total" data-value={f.down_total}>
              {f.down_total}
            </b>
            <small>
              <span data-testid="v-down_7_days" data-value={f.down_7_days}>
                {f.down_7_days}
              </span>{" "}
              in the last 7 days
            </small>
          </dd>
        </div>
      </dl>
      <h3 className="ad-h3">Recent thumbs-down answers</h3>
      {f.recent_down.length === 0 ? (
        <p className="ad-empty" data-testid="down-empty">
          No thumbs-down yet.
        </p>
      ) : (
        <ol className="ad-downs" data-testid="down-list">
          {f.recent_down.map((r) => (
            <li key={r.message_id} className="ad-down" data-testid="down-row" data-message-id={r.message_id} data-trace-id={r.trace_id}>
              <div className="ad-down-meta">
                <span className="ad-when">{fmtUtc(r.at)}</span>
                <span className="ad-down-who" data-testid="down-name">
                  {r.name ?? `user #${r.user_id}`}
                </span>
              </div>
              <p className="ad-down-q" data-testid="down-question">
                {r.question === null ? <em>question not stored</em> : `“${r.question}”`}
              </p>
              <p className="ad-down-a" data-testid="down-answer">
                {r.answer === null ? <em>answer not stored</em> : r.answer}
                {r.answer_truncated && <span className="ad-muted"> … ({r.answer_chars} chars)</span>}
              </p>
              <div className="ad-down-links">
                {r.trace_url ? (
                  <a className="ad-lf" href={r.trace_url} target="_blank" rel="noreferrer noopener" data-testid="open-langfuse">
                    Open in Langfuse
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M7 17L17 7M9 7h8v8" />
                    </svg>
                  </a>
                ) : (
                  <span className="ad-trace mono" data-testid="trace-id-only" title="Langfuse gave no project id (tracing off or unreachable): the trace id alone">
                    trace {r.trace_id}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
      {f.recent_down.length > 0 && !langfuse.project_id && (
        <p className="ad-fine" data-testid="langfuse-note">
          No Langfuse link: {langfuse.host ? "the backend could not learn the project id (tracing off or the host unreachable)" : "no Langfuse host is configured"}, so each row shows its trace id only.
        </p>
      )}
    </div>
  );
}

const ThumbUp = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M7 10v11M3 11h4l3-8a2 2 0 0 1 3 1v5h5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 16.8 21H7" />
  </svg>
);
const ThumbDown = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M17 14V3M21 13h-4l-3 8a2 2 0 0 1-3-1v-5H6a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 7.2 3H17" />
  </svg>
);
