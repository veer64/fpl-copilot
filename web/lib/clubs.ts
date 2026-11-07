/** The 20 clubs of the 2026-27 Premier League (Prompt W4): codes = bootstrap-static teams[].short_name, read live on
 *  6 Nov 2026 (ARS AVL BHA BOU BRE CHE COV CRY EVE FUL HUL IPS LEE LIV MCI MUN NEW NFO SUN TOT). The reference's map
 *  carried WHU and WOL (not in the league: dropped) and lacked COV, HUL, IPS and NEW (added). bg = the club's primary
 *  colour for the next-fixture strip, fg = a text colour at >= 4.5:1 on it (scripts/contrast_clubs.mjs checks every pair). */
export type Club = { code: string; name: string; bg: string; fg: string };

export const CLUBS: Record<string, Club> = {
  ARS: { code: "ARS", name: "Arsenal", bg: "#E60006", fg: "#FFFFFF" },
  AVL: { code: "AVL", name: "Aston Villa", bg: "#670E36", fg: "#FFFFFF" },
  BHA: { code: "BHA", name: "Brighton", bg: "#0057B8", fg: "#FFFFFF" },
  BOU: { code: "BOU", name: "Bournemouth", bg: "#DA291C", fg: "#FFFFFF" },
  BRE: { code: "BRE", name: "Brentford", bg: "#E30613", fg: "#FFFFFF" },
  CHE: { code: "CHE", name: "Chelsea", bg: "#034694", fg: "#FFFFFF" },
  COV: { code: "COV", name: "Coventry City", bg: "#78D0F6", fg: "#0B1A2A" },
  CRY: { code: "CRY", name: "Crystal Palace", bg: "#1B458F", fg: "#FFFFFF" },
  EVE: { code: "EVE", name: "Everton", bg: "#003399", fg: "#FFFFFF" },
  FUL: { code: "FUL", name: "Fulham", bg: "#F5F5F5", fg: "#111111" },
  HUL: { code: "HUL", name: "Hull City", bg: "#F5A12E", fg: "#1A1200" },
  IPS: { code: "IPS", name: "Ipswich Town", bg: "#1E4FA3", fg: "#FFFFFF" },
  LEE: { code: "LEE", name: "Leeds", bg: "#FFFFFF", fg: "#1D428A" },
  LIV: { code: "LIV", name: "Liverpool", bg: "#C8102E", fg: "#FFFFFF" },
  MCI: { code: "MCI", name: "Man City", bg: "#6CABDD", fg: "#04121F" },
  MUN: { code: "MUN", name: "Man Utd", bg: "#DA291C", fg: "#FFFFFF" },
  NEW: { code: "NEW", name: "Newcastle", bg: "#241F20", fg: "#FFFFFF" },
  NFO: { code: "NFO", name: "Nott’m Forest", bg: "#DD0000", fg: "#FFFFFF" },
  SUN: { code: "SUN", name: "Sunderland", bg: "#D81329", fg: "#FFFFFF" },
  TOT: { code: "TOT", name: "Spurs", bg: "#132257", fg: "#FFFFFF" },
};

const UNKNOWN: Club = { code: "???", name: "Unknown", bg: "#2C4052", fg: "#F2FBFF" };

export function club(code: string | null | undefined): Club {
  if (!code) return UNKNOWN;
  return CLUBS[code.toUpperCase()] ?? { ...UNKNOWN, code: code.toUpperCase(), name: code.toUpperCase() };
}
