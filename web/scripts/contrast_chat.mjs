// Prompt W4: the Chat page's text / background pairs (app/chat/chat.css + the references) at >= 4.5:1 (3:1 for the non-text
// hairlines is not checked here). Run: node scripts/contrast_chat.mjs
const BG = "#04070C";
const over = (hex, alpha, base) => {
  const c = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [r1, g1, b1] = c(hex);
  const [r2, g2, b2] = c(base);
  const mix = (a, b) => Math.round(a * alpha + b * (1 - alpha));
  return "#" + [mix(r1, r2), mix(g1, g2), mix(b1, b2)].map((v) => v.toString(16).padStart(2, "0")).join("");
};
const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
};
const CARD = over("#080F18", 0.8, BG);
const BOX = over("#080F18", 0.92, BG);
const POP = over("#060C13", 0.98, BG);
const USER = "#123041";
const pairs = [
  ["body text #DDE8F2 on the page", "#DDE8F2", BG],
  ["strong #F2FBFF on the page", "#F2FBFF", BG],
  ["user bubble text #F2FBFF on #123041", "#F2FBFF", USER],
  ["secondary #A9BACB on the page", "#A9BACB", BG],
  ["subtle #8A9BB0 on the page", "#8A9BB0", BG],
  ["mono grey #6E8093 footer on the page", "#6E8093", BG],
  ["label cyan #7FE9FF on the page", "#7FE9FF", BG],
  ["cyan #3BE8FF table key value on #0B1520", "#3BE8FF", "#0B1520"],
  ["table header #8A9BB0 on #0B1520", "#8A9BB0", "#0B1520"],
  ["table text #DDE8F2 on the table bg", "#DDE8F2", over("#080F18", 0.7, BG)],
  ["chip text #C9D6E3 on the chip", "#C9D6E3", over("#080F18", 0.8, BG)],
  ["sidebar row #E8F6FF on the sidebar", "#E8F6FF", over("#060B11", 0.9, BG)],
  ["sidebar ago #8A9BB0 on the sidebar", "#8A9BB0", over("#060B11", 0.9, BG)],
  ["group label #6E8093 on the sidebar", "#6E8093", over("#060B11", 0.9, BG)],
  ["tag team #9FF2FF on its tint", "#9FF2FF", over("#3BE8FF", 0.12, BG)],
  ["tag general #C9D6E3 on its tint", "#C9D6E3", over("#C9D6E3", 0.1, BG)],
  ["primary button #021016 on #3BE8FF", "#021016", "#3BE8FF"],
  ["secondary button #E8F6FF on its bg", "#E8F6FF", over("#FFFFFF", 0.03, BG)],
  ["composer text #F2FBFF on the box", "#F2FBFF", BOX],
  ["placeholder #7D8EA0 on the box", "#7D8EA0", BOX],
  ["disabled text #6E8093 on the dim box", "#6E8093", over("#080F18", 0.6, BG)],
  ["counter amber #FFC23D on the box", "#FFC23D", BOX],
  ["card line #8A9BB0 on the card", "#8A9BB0", CARD],
  ["card name #F2FBFF on the card", "#F2FBFF", CARD],
  ["footer #6E8093 on the card", "#6E8093", CARD],
  ["token name #F2FBFF on the token", "#F2FBFF", over("#040A10", 0.9, "#0F3B29")],
  ["flag yellow text #1F1600 on #FFC23D", "#1F1600", "#FFC23D"],
  ["flag red text #2A0505 on #FF7A7A", "#2A0505", "#FF7A7A"],
  ["C badge #021016 on #3BE8FF", "#021016", "#3BE8FF"],
  ["VC badge #7FE9FF on #04070C", "#7FE9FF", "#04070C"],
  ["IN tag #032014 on #5BE3A4", "#032014", "#5BE3A4"],
  ["OUT tag #2A0505 on #FF8A7A", "#2A0505", "#FF8A7A"],
  ["hover card name #F2FBFF on the pop", "#F2FBFF", POP],
  ["hover card sub #A9BACB on the pop", "#A9BACB", POP],
  ["hover card stat label #8A9BB0 on the stat bg", "#8A9BB0", over("#FFFFFF", 0.045, POP)],
  ["hover pred cyan #3BE8FF on the stat bg", "#3BE8FF", over("#FFFFFF", 0.045, POP)],
  ["flag line #FFD37A on its tint", "#FFD37A", over("#FFC23D", 0.12, POP)],
  ["flag line red #FFA3A3 on its tint", "#FFA3A3", over("#FF7A7A", 0.14, POP)],
  ["chip box ready #E8F6FF on its tint", "#E8F6FF", over("#3BE8FF", 0.06, CARD)],
  ["chip box ready label #7FE9FF on its tint", "#7FE9FF", over("#3BE8FF", 0.06, CARD)],
  ["chip box used #6E8093 on the card", "#6E8093", CARD],
  ["preview OUT label #FF8A7A on #0B1520", "#FF8A7A", "#0B1520"],
  ["preview IN label #5BE3A4 on #0B1520", "#5BE3A4", "#0B1520"],
  ["preview meta #8A9BB0 on the preview", "#8A9BB0", over("#080F18", 0.85, BG)],
  ["impact value #F2FBFF on its box", "#F2FBFF", over("#FFFFFF", 0.03, over("#080F18", 0.85, BG))],
  ["impact gain #5BE3A4 on its box", "#5BE3A4", over("#FFFFFF", 0.03, over("#080F18", 0.85, BG))],
  ["chosen #9BF0C8 on its tint", "#9BF0C8", over("#5BE3A4", 0.1, BG)],
  ["saved title #F2FBFF on the saved tint", "#F2FBFF", over("#5BE3A4", 0.07, BG)],
  ["saved text #C9D6E3 on the saved tint", "#C9D6E3", over("#5BE3A4", 0.07, BG)],
  ["system title #F2FBFF on the system bg", "#F2FBFF", over("#080F18", 0.85, BG)],
  ["system text #A9BACB on the system bg", "#A9BACB", over("#080F18", 0.85, BG)],
  ["amber note #FFD37A on its tint", "#FFD37A", over("#FFC23D", 0.1, CARD)],
  ["thinking word #E8F6FF on the bubble", "#E8F6FF", over("#080F18", 0.88, BG)],
  ["thinking seconds #7FE9FF on the bubble", "#7FE9FF", over("#080F18", 0.88, BG)],
  ["source pop link #7FE9FF on the pop", "#7FE9FF", POP],
  ["source pop key #8A9BB0 on the pop", "#8A9BB0", POP],
  ["team bar line #A9BACB on the bar", "#A9BACB", over("#0F3B29", 0.6, BG)],
  ["team bar injury #FFC23D on the bar", "#FFC23D", over("#0F3B29", 0.6, BG)],
  ["changes pill #5BE3A4 on its tint", "#5BE3A4", over("#5BE3A4", 0.14, over("#0F3B29", 0.6, BG))],
  ["panel line #8A9BB0 on #060B11", "#8A9BB0", "#060B11"],
  ["bench number #8A9BB0 on the bench", "#8A9BB0", over("#040A10", 0.6, CARD)],
  ["home link #A9BACB on the header", "#A9BACB", over("#04070C", 0.9, BG)],
  ["account initials #021016 on #2398AE", "#021016", "#2398AE"],
];
let worst = Infinity;
let fails = 0;
for (const [name, fg, bg] of pairs) {
  const r = ratio(fg, bg);
  worst = Math.min(worst, r);
  if (r < 4.5) fails++;
  console.log(`${r.toFixed(2).padStart(6)}:1 ${r < 4.5 ? "FAIL" : "ok  "} ${name}`);
}
console.log(`${pairs.length} pairs, lowest ${worst.toFixed(2)}:1, ${fails} below 4.5:1`);
process.exit(fails ? 1 : 0);
