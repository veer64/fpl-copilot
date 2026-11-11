"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { toast } from "sonner";
import { ApiError, api, type AdminSummary } from "@/lib/api";
import { useResource } from "@/components/home/useResource";
import { ErrorBox } from "@/components/home/ErrorBox";
import { PublicHeader } from "@/components/public/PublicChrome";
import { FeedbackCard } from "./FeedbackCard";
import { SignupsChart } from "./SignupsChart";
import { UsersTable } from "./UsersTable";
import { fmtUsd, fmtUtc, methodLabel, pct } from "./format";
import { loginSignedOut, useSignedOutRedirect } from "@/lib/session";

/** /admin (Prompt W6): the owner's basic dashboard -- everything on it is ONE read, GET /admin/summary, with the browser's
 *  Clerk token; "Refresh" reads it again (no polling). Signed out: the server page already sent the visitor to /login; signed
 *  in but not the admin: the backend answers 403 and the page goes silently to /home. Built from the existing pieces: the
 *  About / Privacy header (logo, Home, music, account menu), Home's glass cards and corner brackets, buttons and tags. */
export function AdminExperience() {
  const router = useRouter();
  const { getToken } = useAuth();
  const [summary, reload] = useResource(api.adminSummary);
  const [downloading, setDownloading] = useState(false);
  useSignedOutRedirect();

  useEffect(() => {
    if (summary.status !== "error") return;
    if (summary.error.status === 403) router.replace("/home");
    else if (summary.error.status === 401) loginSignedOut(router);
  }, [summary, router]);

  const download = async () => {
    setDownloading(true);
    try {
      const csv = await api.adminUsersCsv(getToken);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "users.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (err) {
      toast.error(`Couldn’t download the CSV: ${err instanceof ApiError ? err.detail : "the API could not be reached"}`);
    } finally {
      setDownloading(false);
    }
  };

  const ready = summary.status === "ready";
  const refused = summary.status === "error" && (summary.error.status === 403 || summary.error.status === 401);
  return (
    <div className="pp ad" data-testid="admin" data-state={summary.status}>
      <div aria-hidden="true" className="pp-glow" />
      <div aria-hidden="true" className="pp-grid" />
      <PublicHeader />
      <main className="ad-main">
        <div className="ad-head">
          <div>
            <span className="pp-eyebrow">OWNER ONLY</span>
            <h1>Admin</h1>
            <p className="ad-sub" data-testid="as-of">
              {ready ? `As of ${fmtUtc(summary.data.at)} · all days are UTC` : "All days are UTC."}
            </p>
          </div>
          <button type="button" className="hm-btn-o" onClick={reload} disabled={summary.status === "loading"} data-testid="refresh">
            {summary.status === "loading" ? <span className="hm-spin" aria-hidden="true" /> : <RefreshIcon />}
            Refresh
          </button>
        </div>

        {summary.status === "loading" && <Skeleton />}
        {summary.status === "error" && !refused && <ErrorBox what="admin data" error={summary.error} onRetry={reload} className="ad-err" />}
        {ready && <Dashboard s={summary.data} onDownload={download} downloading={downloading} />}
      </main>
    </div>
  );
}

function Dashboard({ s, onDownload, downloading }: { s: AdminSummary; onDownload: () => void; downloading: boolean }) {
  const methods = ["google", "email", ...Object.keys(s.sign_in_methods).filter((m) => m !== "google" && m !== "email").sort()];
  const methodTotal = Object.values(s.sign_in_methods).reduce((a, n) => a + n, 0);
  return (
    <>
      <section className="ad-sec" aria-labelledby="h-numbers">
        <h2 id="h-numbers" className="ad-h2">
          Top numbers
        </h2>
        <div className="ad-tiles" data-testid="tiles">
          <Tile label="Total users (real people)" testid="tile-users">
            <V k="users_total" v={s.users_total} />
          </Tile>
          <Tile label="Sign-ups · today / 7 days" testid="tile-signups">
            <V k="sign_ups_today" v={s.sign_ups_today} />
            <i>/</i>
            <V k="sign_ups_7_days" v={s.sign_ups_7_days} />
          </Tile>
          <Tile label="Active · today / 7 days" testid="tile-active">
            <V k="active_today" v={s.active_today} />
            <i>/</i>
            <V k="active_7_days" v={s.active_7_days} />
          </Tile>
          <Tile label="Answers · today / total" testid="tile-answers">
            <V k="answers_today" v={s.answers_today} />
            <i>/</i>
            <V k="answers_total" v={s.answers_total} />
          </Tile>
          <Tile label="Spend · today / month / total" testid="tile-spend" small>
            <V k="usd_today" v={s.usd_today} usd />
            <i>/</i>
            <V k="usd_month" v={s.usd_month} usd />
            <i>/</i>
            <V k="usd_total" v={s.usd_total} usd />
          </Tile>
        </div>
      </section>

      <Card title="Sign-ups per day" sub="Last 30 days, UTC" id="h-signups" testid="card-signups">
        <SignupsChart days={s.sign_ups_per_day} />
      </Card>

      <Card title="Users" sub="Click a column to sort" id="h-users" testid="card-users">
        <UsersTable users={s.users} deleted={s.deleted_accounts} owner={s.owner_use} testing={s.testing_use} onDownload={onDownload} downloading={downloading} />
      </Card>

      <div className="ad-grid2">
        <Card title="Daily-limit hits" sub={`Last 30 days · ${s.cap_hits_today} today, ${s.cap_hits_total} all time`} id="h-hits" testid="card-hits">
          {s.cap_hits.length === 0 ? (
            <p className="ad-empty" data-testid="hits-empty">
              No limit hits in the last 30 days.
            </p>
          ) : (
            <ul className="ad-list" data-testid="cap-hits">
              {s.cap_hits.map((h, i) => (
                <li key={`${h.user_id}-${h.at}-${i}`} className="ad-hit" data-testid="cap-hit">
                  <div>
                    <span className="ad-row-title">{h.name ?? `user #${h.user_id}`}</span>
                    <span className="ad-email ad-muted">{h.email ?? ""}</span>
                  </div>
                  <div className="ad-hit-right">
                    <span className="ad-when">{fmtUtc(h.at)}</span>
                    <span className="hm-tag hm-tag-ago">
                      {fmtUsd(h.spent_usd)} of {fmtUsd(h.cap_usd)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Sign-in split" sub="How accounts signed up" id="h-split" testid="card-split">
          {methodTotal === 0 ? (
            <p className="ad-empty">No users yet.</p>
          ) : (
            <ul className="ad-split" data-testid="signin-split">
              {methods.map((m) => {
                const n = s.sign_in_methods[m] ?? 0;
                if (n === 0 && m !== "google" && m !== "email") return null;
                return (
                  <li key={m} data-testid={`signin-${m}`} data-count={n} data-pct={methodTotal ? Math.round((n / methodTotal) * 100) : 0}>
                    <div className="ad-split-head">
                      <span className="ad-row-title">{methodLabel(m)}</span>
                      <span className="mono ad-split-n">
                        {n} · {pct(n, methodTotal)}
                      </span>
                    </div>
                    <div className="ad-meter" aria-hidden="true">
                      <span style={{ width: pct(n, methodTotal) }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Thumbs" sub="What users said about their answers" id="h-thumbs" testid="card-thumbs">
        <FeedbackCard feedback={s.feedback} langfuse={s.langfuse} />
      </Card>
    </>
  );
}

function Tile({ label, children, testid, small }: { label: string; children: React.ReactNode; testid: string; small?: boolean }) {
  return (
    <div className={`hm-glass ad-tile${small ? " small" : ""}`} data-testid={testid}>
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <span className="ad-tile-lbl">{label}</span>
      <span className="ad-tile-v">{children}</span>
    </div>
  );
}

/** one number of the summary, with its raw value on the element for the checks */
function V({ k, v, usd }: { k: string; v: number; usd?: boolean }) {
  return (
    <b data-testid={`v-${k}`} data-value={v}>
      {usd ? fmtUsd(v) : v}
    </b>
  );
}

function Card({ title, sub, id, testid, children }: { title: string; sub?: string; id: string; testid: string; children: React.ReactNode }) {
  return (
    <section className="hm-glass ad-card" aria-labelledby={id} data-testid={testid}>
      <span className="hm-br hm-tl" aria-hidden="true" />
      <span className="hm-br hm-brr" aria-hidden="true" />
      <div className="ad-card-head">
        <h2 id={id} className="ad-h2">
          {title}
        </h2>
        {sub && <span className="hm-count">{sub}</span>}
      </div>
      {children}
    </section>
  );
}

function Skeleton() {
  return (
    <div className="ad-skel" role="status" aria-busy="true" aria-label="Loading" data-testid="admin-skeleton">
      <div className="ad-tiles" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <div className="hm-glass ad-tile" key={i}>
            <span className="hm-skel" style={{ width: "60%", height: 10 }} />
            <span className="hm-skel" style={{ width: "45%", height: 30, marginTop: 10 }} />
          </div>
        ))}
      </div>
      {[0, 1, 2].map((i) => (
        <div className="hm-glass ad-card" key={i} aria-hidden="true">
          <span className="hm-skel" style={{ width: 160, height: 18 }} />
          <span className="hm-skel" style={{ width: "100%", height: i === 0 ? 150 : 90, marginTop: 16 }} />
        </div>
      ))}
    </div>
  );
}

const RefreshIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" />
  </svg>
);
