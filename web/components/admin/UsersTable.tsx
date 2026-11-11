"use client";

import { useMemo, useState } from "react";
import type { AdminUser } from "@/lib/api";
import { fmtUsd, fmtUtc, methodLabel } from "./format";

type Col = "name" | "email" | "sign_in_method" | "joined" | "last_active" | "answers" | "usd";
const COLS: { key: Col; label: string; num?: boolean }[] = [
  { key: "name", label: "Name" },
  { key: "email", label: "Email" },
  { key: "sign_in_method", label: "Sign-in" },
  { key: "joined", label: "Joined (UTC)" },
  { key: "last_active", label: "Last active (UTC)" },
  { key: "answers", label: "Answers", num: true },
  { key: "usd", label: "$ spent", num: true },
];

/** nulls last whichever way the sort goes; strings case-insensitive; ISO instants compare as text */
function compare(a: AdminUser, b: AdminUser, col: Col, dir: 1 | -1): number {
  const x = a[col];
  const y = b[col];
  if (x === null && y === null) return 0;
  if (x === null) return 1;
  if (y === null) return -1;
  if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
  return String(x).localeCompare(String(y), "en", { sensitivity: "base" }) * dir;
}

/** The users table (Prompt W6): click a header to sort (default: last active, newest first); the row of the anonymous
 *  cost rows of deleted accounts (spend only) closes the table; "Download CSV" is the caller's (the P7 file with the token). */
type Line = { answers: number; usd: number };

/** W7b: real people only in the rows; the deleted accounts' spend is in the totals, the owner's own use and the pre-launch
 *  testing are shown as two grey lines that are NOT in the totals. */
export function UsersTable({ users, deleted, owner, testing, onDownload, downloading }: { users: AdminUser[]; deleted: Line; owner?: Line; testing?: Line; onDownload: () => void; downloading: boolean }) {
  const [sort, setSort] = useState<{ col: Col; dir: 1 | -1 }>({ col: "last_active", dir: -1 });
  const rows = useMemo(() => [...users].sort((a, b) => compare(a, b, sort.col, sort.dir) || a.user_id - b.user_id), [users, sort]);
  const click = (col: Col) => setSort((s) => (s.col === col ? { col, dir: s.dir === 1 ? -1 : 1 } : { col, dir: col === "name" || col === "email" || col === "sign_in_method" ? 1 : -1 }));
  return (
    <div className="ad-table-wrap">
      <table className="ad-table" data-testid="users-table" data-sort={sort.col} data-dir={sort.dir === 1 ? "asc" : "desc"} data-rows={rows.length}>
        <thead>
          <tr>
            {COLS.map((c) => (
              <th key={c.key} scope="col" aria-sort={sort.col === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={c.num ? "n" : undefined}>
                <button type="button" className="ad-sort" onClick={() => click(c.key)} data-testid={`sort-${c.key}`}>
                  {c.label}
                  <span className="ad-arrow" aria-hidden="true">
                    {sort.col === c.key ? (sort.dir === 1 ? "↑" : "↓") : "↕"}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={COLS.length} className="ad-empty-cell">
                No users yet.
              </td>
            </tr>
          )}
          {rows.map((u) => (
            <tr key={u.user_id} data-testid="user-row" data-user-id={u.user_id}>
              <td className="ad-name">
                {u.name ?? "—"}
                {u.is_admin && <span className="hm-tag hm-tag-team ad-tag">ADMIN</span>}
              </td>
              <td className="ad-email">{u.email ?? "—"}</td>
              <td>{methodLabel(u.sign_in_method)}</td>
              <td className="ad-when">{fmtUtc(u.joined)}</td>
              <td className="ad-when">{fmtUtc(u.last_active)}</td>
              <td className="n">{u.answers}</td>
              <td className="n">{fmtUsd(u.usd)}</td>
            </tr>
          ))}
          {(deleted.answers > 0 || deleted.usd > 0) && (
            <tr className="ad-deleted" data-testid="deleted-row" data-usd={deleted.usd} data-answers={deleted.answers}>
              <td className="ad-name">Deleted accounts</td>
              <td colSpan={4} className="ad-muted">
                anonymous cost rows kept after account deletion — in the totals, spend only
              </td>
              <td className="n ad-muted">—</td>
              <td className="n">{fmtUsd(deleted.usd)}</td>
            </tr>
          )}
          {owner && (owner.answers > 0 || owner.usd > 0) && (
            <tr className="ad-deleted ad-grey" data-testid="owner-row" data-usd={owner.usd} data-answers={owner.answers}>
              <td className="ad-name ad-muted">Your own use (owner)</td>
              <td colSpan={4} className="ad-muted">
                not in the totals
              </td>
              <td className="n ad-muted">{owner.answers}</td>
              <td className="n ad-muted">{fmtUsd(owner.usd)}</td>
            </tr>
          )}
          {testing && (testing.answers > 0 || testing.usd > 0) && (
            <tr className="ad-deleted ad-grey" data-testid="testing-row" data-usd={testing.usd} data-answers={testing.answers}>
              <td className="ad-name ad-muted">Before launch: testing</td>
              <td colSpan={4} className="ad-muted">
                answers from before accounts existed and the reserved test accounts — not in the totals
              </td>
              <td className="n ad-muted">{testing.answers}</td>
              <td className="n ad-muted">{fmtUsd(testing.usd)}</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="ad-table-foot">
        <span className="hm-count">
          {rows.length} user{rows.length === 1 ? "" : "s"}
        </span>
        <button type="button" className="hm-btn-o" onClick={onDownload} disabled={downloading} data-testid="download-csv">
          {downloading ? <span className="hm-spin" aria-hidden="true" /> : null}
          Download CSV
        </button>
      </div>
    </div>
  );
}
