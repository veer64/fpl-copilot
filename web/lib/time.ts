/** Clock words for the Home page (Prompt W3): the greeting, "time ago", the deadline pill. All in the browser's local time. */

export function greetingWord(d: Date = new Date()): "Morning" | "Afternoon" | "Evening" {
  const h = d.getHours();
  return h < 12 ? "Morning" : h < 18 ? "Afternoon" : "Evening";
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "2h ago", "Yesterday", "3d ago" -- the recent-chats column. */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, now.getTime() - t);
  if (diff < MIN) return "just now";
  if (diff < HOUR) return `${Math.floor(diff / MIN)}m ago`;
  if (diff < DAY && startOfDay(now) <= t) return `${Math.floor(diff / HOUR)}h ago`;
  const days = Math.round((startOfDay(now) - startOfDay(new Date(t))) / DAY);
  if (days <= 1) return "Yesterday";
  if (days < 14) return `${days}d ago`;
  if (days < 60) return `${Math.floor(days / 7)}w ago`;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The grey tag on a team card that is not the last-used one: "3 DAYS AGO", "TODAY", "NOT USED YET". */
export function usedAgoTag(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "NOT USED YET";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "NOT USED YET";
  const days = Math.round((startOfDay(now) - startOfDay(new Date(t))) / DAY);
  if (days <= 0) return "TODAY";
  if (days === 1) return "YESTERDAY";
  if (days < 14) return `${days} DAYS AGO`;
  const weeks = Math.floor(days / 7);
  return weeks === 1 ? "1 WEEK AGO" : `${weeks} WEEKS AGO`;
}

/** "Fri 6 Nov · 18:30" in the browser's local time zone; the words in the brief's order (day before month) whatever the
 *  browser's locale, the time 24-hour. */
export function formatDeadline(iso: string): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }).replace(",", "");
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day} · ${time}`;
}

/** "in 1 d 4 h", "in 3 h 12 m", "in 12 m", "now". */
export function countdown(iso: string, now: Date = new Date()): string {
  const left = new Date(iso).getTime() - now.getTime();
  if (!(left > 0)) return "now";
  const d = Math.floor(left / DAY);
  const h = Math.floor((left % DAY) / HOUR);
  const m = Math.floor((left % HOUR) / MIN);
  if (d > 0) return `in ${d} d ${h} h`;
  if (h > 0) return `in ${h} h ${m} m`;
  return `in ${Math.max(1, m)} m`;
}

/** The first deadline still ahead, or null. */
export function nextEvent<T extends { deadline_time: string }>(events: T[], now: Date = new Date()): T | null {
  return events.find((e) => new Date(e.deadline_time).getTime() > now.getTime()) ?? null;
}

/** "1,234,567" */
export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toLocaleString("en-GB");
}

/** Up to two initials: "Veer Sanghavi" -> "VS", "veer@x" -> "V". */
export function initials(name: string | null | undefined, email: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (email ?? "?").charAt(0).toUpperCase();
}

/** The team's short name for a tag: the label in capitals, at most 16 characters. */
export function shortTeamName(label: string | null | undefined): string {
  const s = (label ?? "").trim().toUpperCase();
  if (!s) return "TEAM";
  return s.length <= 16 ? s : s.slice(0, 15).trimEnd() + "…";
}
