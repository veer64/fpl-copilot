// Prompt W4: every club strip (lib/clubs.ts) must put its text at >= 4.5:1 on its primary colour. Run: node scripts/contrast_clubs.mjs
import fs from "node:fs";

const src = fs.readFileSync(new URL("../lib/clubs.ts", import.meta.url), "utf8");
const rows = [...src.matchAll(/(\w{3}): \{ code: "\w{3}", name: "([^"]+)", bg: "(#[0-9A-Fa-f]{6})", fg: "(#[0-9A-Fa-f]{6})" \}/g)];
const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
};
let worst = Infinity;
let fails = 0;
for (const [, code, name, bg, fg] of rows) {
  const r = ratio(bg, fg);
  worst = Math.min(worst, r);
  if (r < 4.5) fails++;
  console.log(`${code} ${name.padEnd(16)} ${bg} on ${fg}  ${r.toFixed(2)}:1 ${r < 4.5 ? "FAIL" : "ok"}`);
}
console.log(`${rows.length} clubs, lowest ${worst.toFixed(2)}:1, ${fails} below 4.5:1`);
process.exit(fails ? 1 : 0);
