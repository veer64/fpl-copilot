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

/** "6h 12m", "1d 4h", "12m", "now" -- the phone's compact deadline chip (Prompt W4). */
export function countdownShort(iso: string, now: Date = new Date()): string {
  const left = new Date(iso).getTime() - now.getTime();
  if (!(left > 0)) return "now";
  const d = Math.floor(left / DAY);
  const h = Math.floor((left % DAY) / HOUR);
  const m = Math.floor((left % HOUR) / MIN);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${Math.max(1, m)}m`;
}

/** "now", "2h", "1d", "3d" -- the past-chats rows (the Chat page's references). */
export function agoShort(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, now.getTime() - t);
  if (diff < MIN) return "now";
  if (diff < HOUR) return `${Math.floor(diff / MIN)}m`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h`;
  const days = Math.max(1, Math.round((startOfDay(now) - startOfDay(new Date(t))) / DAY));
  if (days < 14) return `${days}d`;
  if (days < 60) return `${Math.floor(days / 7)}w`;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** TODAY / YESTERDAY / EARLIER in the browser's local time (the sidebar groups). */
export function dayGroup(iso: string, now: Date = new Date()): "TODAY" | "YESTERDAY" | "EARLIER" {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "EARLIER";
  const days = Math.round((startOfDay(now) - startOfDay(new Date(t))) / DAY);
  return days <= 0 ? "TODAY" : days === 1 ? "YESTERDAY" : "EARLIER";
}

/** "3 Nov" (the source chip) and "3 NOV 2026" (the pop-up), from an ISO day. */
export function dayShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
export function dayLong(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).toUpperCase();
}

/** "Fri 6 Nov, 09:00 UTC" (the team card's predictions footer). */
export function stampUtc(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).replace(",", "");
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
  return `${day}, ${time} UTC`;
}

/** "3 h 12 m" / "42 m" / "0:42" -- the system messages' countdowns. */
export function leftWords(iso: string, now: Date): string {
  const left = Math.max(0, new Date(iso).getTime() - now.getTime());
  const h = Math.floor(left / HOUR);
  const m = Math.floor((left % HOUR) / MIN);
  return h > 0 ? `${h} h ${m} m` : `${m} m`;
}
export function leftClock(untilMs: number, nowMs: number): string {
  const s = Math.max(0, Math.ceil((untilMs - nowMs) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
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
