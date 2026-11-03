// Prompt W1 A7: WCAG 2.x contrast of every text token on the background it sits on (computed, not eyeballed).
// Translucent layers are composited onto the page background first. Usage: node scripts/contrast.mjs
const hex = (h) => {
  const s = h.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16));
};
const over = (top, alpha, under) => top.map((c, i) => Math.round(c * alpha + under[i] * (1 - alpha)));
const lum = ([r, g, b]) => {
  const f = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
};

const BG = hex("#04070C");
const CARD = over(hex("#060C14"), 0.84, BG); // rgba(6,12,20,.84) over the page (the blur does not change the colour)
const CARD_M = over(hex("#060C14"), 0.88, BG); // mobile card
const INPUT = over([255, 255, 255], 0.03, CARD); // rgba(255,255,255,.03) over the card
const PILL = over(hex("#060C14"), 0.6, BG); // rgba(6,12,20,.6) sound / skip pills
const GOOGLE = hex("#EEF3F8");
const ACCENT = hex("#3BE8FF");
const ACCENT_HOVER = hex("#7CF3FF");

const checks = [
  ["text #E8F6FF on bg", "#E8F6FF", BG],
  ["text-strong #F2FBFF (h1) on bg", "#F2FBFF", BG],
  ["accent-text #7FE9FF (eyebrows, HUD) on bg", "#7FE9FF", BG],
  ["text-secondary #C9D6E3 (labels, pills) on bg", "#C9D6E3", BG],
  ["text-secondary #C9D6E3 on pill rgba(6,12,20,.6)", "#C9D6E3", PILL],
  ["text-muted #A9BACB (card body) on card", "#A9BACB", CARD],
  ["text-subtle #8A9BB0 (fine print, OR) on card", "#8A9BB0", CARD],
  ["text-subtle #8A9BB0 (gate music line) on bg", "#8A9BB0", BG],
  ["placeholder #7D8EA0 on input", "#7D8EA0", INPUT],
  ["input text #E8F6FF on input", "#E8F6FF", INPUT],
  ["h2 #E8F6FF on card", "#E8F6FF", CARD],
  ["accent-text #7FE9FF (card eyebrow) on card", "#7FE9FF", CARD],
  ["label #C9D6E3 on card", "#C9D6E3", CARD],
  ["on-accent #021016 on accent #3BE8FF (CTA)", "#021016", ACCENT],
  ["on-accent #021016 on accent-hover #7CF3FF", "#021016", ACCENT_HOVER],
  ["google-text #0B1118 on google-bg #EEF3F8", "#0B1118", GOOGLE],
  ["error #FF8A7A on card", "#FF8A7A", CARD],
  ["error #FF8A7A on mobile card", "#FF8A7A", CARD_M],
  ["link #9FB3C8 (Privacy / About) on bg", "#9FB3C8", BG],
  ["ticker #8FA3B8 on bg", "#8FA3B8", BG],
  ["gate lead #B8C7D6 on bg", "#B8C7D6", BG],
  ["tag #C6F7FF on bg", "#C6F7FF", BG],
  ["tag name #F2FDFF on bg", "#F2FDFF", BG],
  ["text-muted #A9BACB on mobile card", "#A9BACB", CARD_M],
  ["text-subtle #8A9BB0 on mobile card", "#8A9BB0", CARD_M],
  ["OTP digit #E8F6FF on input", "#E8F6FF", INPUT],
];
const nonText = [
  ["control-border #56687A on card (non-text, >= 3:1)", "#56687A", CARD, 3],
  ["focus ring #3BE8FF on bg (non-text, >= 3:1)", "#3BE8FF", BG, 3],
  ["ghost-border #3A4B5C on bg (decorative pill border)", "#3A4B5C", BG, 0],
];

let worst = Infinity;
let fails = 0;
for (const [name, fg, bg] of checks) {
  const r = ratio(hex(fg), bg);
  worst = Math.min(worst, r);
  if (r < 4.5) fails++;
  console.log(`${r >= 4.5 ? "PASS" : "FAIL"}  ${r.toFixed(2)}:1  ${name}`);
}
for (const [name, fg, bg, min] of nonText) {
  const r = ratio(hex(fg), bg);
  console.log(`${min === 0 ? "info" : r >= min ? "PASS" : "FAIL"}  ${r.toFixed(2)}:1  ${name}`);
  if (min && r < min) fails++;
}
console.log(`\ntext tokens: ${checks.length}, lowest ${worst.toFixed(2)}:1, failures ${fails}`);
process.exit(fails ? 1 : 0);
