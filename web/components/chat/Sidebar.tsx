"use client";

import type { ThreadRow } from "@/lib/api";
import { agoShort, dayGroup, shortTeamName } from "@/lib/time";
import type { Resource } from "@/components/home/useResource";

export const COLLAPSE_KEY = "fpl.chat.sidebar";

export function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "collapsed";
  } catch {
    return false;
  }
}
export function writeCollapsed(v: boolean) {
  try {
    window.localStorage.setItem(COLLAPSE_KEY, v ? "collapsed" : "open");
  } catch {
    /* private mode: the choice lasts the session only */
  }
}

export function threadTag(t: Pick<ThreadRow, "fpl_team_id" | "team_name" | "team_label">): { text: string; cls: string } {
  if (t.fpl_team_id) return { text: shortTeamName(t.team_name ?? t.team_label), cls: "ch-tag ch-tag-team" };
  return { text: "GENERAL", cls: "ch-tag ch-tag-gen" };
}

const GROUPS = ["TODAY", "YESTERDAY", "EARLIER"] as const;

/** The past-chats list: grouped TODAY / YESTERDAY / EARLIER in local time, newest first; the open chat tinted with its left
 *  bar; a "NOW · New chat · not sent yet" row for an unsent chat. Used by the desktop sidebar and the phone drawer. */
export function ThreadList({
  threads,
  currentId,
  newRow,
  now,
  onOpen,
  onDelete,
}: {
  threads: Resource<ThreadRow[]>;
  currentId: string | null;
  newRow: { text: string; cls: string } | null;
  now: Date | null;
  onOpen: (t: ThreadRow) => void;
  /** Prompt W5: the trash button on each row (desktop: on hover / focus-within; the phone drawer: always, 44px) */
  onDelete?: (t: ThreadRow) => void;
}) {
  if (threads.status === "loading") {
    return (
      <div className="ch-sk-side" aria-label="Loading past chats" aria-busy="true" data-testid="threads-skeleton">
        <span className="ch-sk" style={{ height: 9, width: "60%" }} />
        {[1, 0.88, 0.76].map((w, i) => (
          <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="ch-sk" style={{ height: 12, width: `${w * 100}%` }} />
            <span className="ch-sk" style={{ height: 10, width: "50%" }} />
          </div>
        ))}
      </div>
    );
  }
  const rows = threads.status === "ready" ? threads.data : [];
  const at = now ?? new Date();
  const grouped = GROUPS.map((g) => ({ label: g, items: rows.filter((t) => dayGroup(t.updated_at, at) === g) })).filter((g) => g.items.length);
  return (
    <nav aria-label="Past chats list" className="ch-side-list" data-testid="thread-list">
      {newRow && (
        <>
          <span className="ch-grp">NOW</span>
          <div className="ch-row on" aria-current="page" data-testid="thread-row-new">
            <span className="ch-row-title">New chat</span>
            <span className="ch-row-meta">
              <span className={newRow.cls}>{newRow.text}</span>
              <span className="ch-row-ago">not sent yet</span>
            </span>
          </div>
        </>
      )}
      {threads.status === "error" && <span className="ch-side-empty">Couldn’t load your past chats.</span>}
      {threads.status === "ready" && rows.length === 0 && !newRow && <span className="ch-side-empty">No chats yet.</span>}
      {grouped.map((g) => (
        <div key={g.label} data-testid={`group-${g.label.toLowerCase()}`} style={{ display: "contents" }}>
          <span className="ch-grp">{g.label}</span>
          {g.items.map((t) => {
            const tag = threadTag(t);
            const on = t.thread_id === currentId;
            const title = t.title ?? "New chat";
            return (
              <div className={`ch-rowwrap${on ? " on" : ""}`} key={t.thread_id} data-testid="thread-rowwrap" data-thread-id={t.thread_id}>
                <button type="button" className={`ch-row${on ? " on" : ""}`} onClick={() => onOpen(t)} aria-current={on ? "page" : undefined} data-testid="thread-row" data-thread-id={t.thread_id}>
                  <span className="ch-row-title">{title}</span>
                  <span className="ch-row-meta">
                    <span className={tag.cls}>{tag.text}</span>
                    <span className="ch-row-ago">{agoShort(t.updated_at, at)}</span>
                  </span>
                </button>
                {onDelete && (
                  <button type="button" className="ch-row-del" onClick={() => onDelete(t)} aria-label={`Delete chat: ${title}`} data-testid="thread-delete" data-thread-id={t.thread_id}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
                    </svg>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export function Sidebar({
  collapsed,
  onToggle,
  onNew,
  ...list
}: {
  collapsed: boolean;
  onToggle: () => void;
  onNew: () => void;
  threads: Resource<ThreadRow[]>;
  currentId: string | null;
  newRow: { text: string; cls: string } | null;
  now: Date | null;
  onOpen: (t: ThreadRow) => void;
  onDelete?: (t: ThreadRow) => void;
}) {
  return (
    <aside aria-label="Past chats" className={`ch-side${collapsed ? " collapsed" : ""}`} data-testid="sidebar" data-collapsed={collapsed}>
      <div className="ch-side-top">
        <button type="button" className="ch-btn-p ch-new" onClick={onNew} aria-label="New chat" data-testid="new-chat">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span>New chat</span>
        </button>
        <button type="button" className="ch-ib" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={onToggle} data-testid="collapse-sidebar">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: collapsed ? "scaleX(-1)" : undefined }}>
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M9 4v16M15 10l-2 2 2 2" />
          </svg>
        </button>
      </div>
      <span className="ch-lbl ch-side-lbl">Past chats</span>
      {!collapsed && <ThreadList {...list} />}
    </aside>
  );
}
