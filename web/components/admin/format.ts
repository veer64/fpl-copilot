/** Formatting for the admin page (Prompt W6): every instant is shown in UTC and says so; money is USD to 2 dp. */

const UTC_DT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
const UTC_DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const UTC_DAY_YEAR = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** "10 Nov 2026 14:03 UTC"; "—" for null. */
export function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${UTC_DT.format(d).replace(",", "")} UTC`;
}

/** "10 Nov" for a "2026-11-10" day. */
export function fmtDay(day: string): string {
  return UTC_DAY.format(new Date(`${day}T00:00:00Z`));
}

/** "10 Nov 2026" for a "2026-11-10" day. */
export function fmtDayYear(day: string): string {
  return UTC_DAY_YEAR.format(new Date(`${day}T00:00:00Z`));
}

export function fmtUsd(n: number): string {
  return `$${(Number.isFinite(n) ? n : 0).toFixed(2)}`;
}

export function pct(part: number, whole: number): string {
  if (!whole) return "0%";
  return `${Math.round((part / whole) * 100)}%`;
}

export function methodLabel(m: string | null): string {
  if (m === "google") return "Google";
  if (m === "email") return "Email code";
  return m ? m : "Other";
}
