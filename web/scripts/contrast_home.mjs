// Prompt W3: WCAG 2.x contrast of every text token on the Home page on the surface it sits on (computed, not eyeballed).
// Translucent layers are composited onto the page background first. Usage: node scripts/contrast_home.mjs
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
const GLASS = over(hex("#080F18"), 0.8, BG); // rgba(8,15,24,.8): team / general / recent cards
const GLASS_M = over(hex("#080F18"), 0.82, BG); // mobile glass
const PILL = over(hex("#080F18"), 0.75, BG); // the deadline pill
const ACCT = over(hex("#080F18"), 0.7, BG); // the account button
const MENU = over(hex("#080F18"), 0.96, BG); // the account menu
const DIALOG = over(hex("#080F18"), 0.96, BG);
const INPUT = over([255, 255, 255], 0.03, DIALOG); // the dialog's input
const IDCHIP = hex("#0B1520");
const ROWICON = hex("#0E1A26");
const CHIP = over(hex("#3BE8FF"), 0.05, GLASS); // rgba(59,232,255,.05) over the glass
const CHIP_HOVER = over(hex("#3BE8FF"), 0.14, GLASS);
const BTN_O = over(hex("#3BE8FF"), 0.06, GLASS);
const BTN_S = over([255, 255, 255], 0.03, GLASS);
const TAG_TEAM = over(hex("#3BE8FF"), 0.12, GLASS);
const TAG_GEN = over(hex("#C9D6E3"), 0.1, GLASS);
const TAG_AGO = over(hex("#C9D6E3"), 0.08, GLASS);
const ADD = over(hex("#3BE8FF"), 0.03, BG); // the dashed Add team card
const ACCENT = hex("#3BE8FF");
const ACCENT_HOVER = hex("#7CF3FF");
const HELP = over([255, 255, 255], 0.03, DIALOG);

const checks = [
  ["h1 #F2FBFF on bg", "#F2FBFF", BG],
  ["greeting sub #A9BACB on bg", "#A9BACB", BG],
  ["eyebrow / section label #7FE9FF on bg", "#7FE9FF", BG],
  ["count #8A9BB0 ('2 of 3 teams') on bg", "#8A9BB0", BG],
  ["brand #E8F6FF on bg", "#E8F6FF", BG],
  ["pill text #C9D6E3 on pill", "#C9D6E3", PILL],
  ["pill GW #7FE9FF on pill", "#7FE9FF", PILL],
  ["pill countdown #F2FBFF on pill", "#F2FBFF", PILL],
  ["account chevron #C9D6E3 on account button", "#C9D6E3", ACCT],
  ["avatar initials #021016 on accent gradient (lighter end)", "#021016", ACCENT],
  ["avatar initials #021016 on gradient darker end #2398AE", "#021016", hex("#2398AE")],
  ["menu name #F2FBFF on menu", "#F2FBFF", MENU],
  ["menu email #A9BACB on menu", "#A9BACB", MENU],
  ["Sign out #FF8A7A on menu", "#FF8A7A", MENU],
  ["team name #F2FBFF on glass", "#F2FBFF", GLASS],
  ["manager #A9BACB on glass", "#A9BACB", GLASS],
  ["stat label #8A9BB0 on glass", "#8A9BB0", GLASS],
  ["stat value #F2FBFF on glass", "#F2FBFF", GLASS],
  ["freshness #8A9BB0 on glass", "#8A9BB0", GLASS],
  ["refresh failed #FF8A7A on glass", "#FF8A7A", GLASS],
  ["Refresh text button #9FB3C8 on glass", "#9FB3C8", GLASS],
  ["ID chip #C9D6E3 on chip bg #0B1520", "#C9D6E3", IDCHIP],
  ["ID chip 'ID' #8A9BB0 on chip bg", "#8A9BB0", IDCHIP],
  ["LAST USED #021016 on accent", "#021016", ACCENT],
  ["ago tag #A9BACB on tag", "#A9BACB", TAG_AGO],
  ["primary button #021016 on accent", "#021016", ACCENT],
  ["primary hover #021016 on #7CF3FF", "#021016", ACCENT_HOVER],
  ["secondary button #E8F6FF on its bg", "#E8F6FF", BTN_S],
  ["outline button #DDF7FF on its bg", "#DDF7FF", BTN_O],
  ["Add team title #F2FBFF on add card", "#F2FBFF", ADD],
  ["Add team sub #A9BACB on add card", "#A9BACB", ADD],
  ["slots left #7FE9FF on add card", "#7FE9FF", ADD],
  ["general title #F2FBFF on glass", "#F2FBFF", GLASS],
  ["general sub #A9BACB on glass", "#A9BACB", GLASS],
  ["TRY ASKING #8A9BB0 on glass", "#8A9BB0", GLASS],
  ["chip text #DDF7FF on chip", "#DDF7FF", CHIP],
  ["chip text #DDF7FF on chip hover", "#DDF7FF", CHIP_HOVER],
  ["recent title #E8F6FF on glass", "#E8F6FF", GLASS],
  ["recent ago #8A9BB0 on glass", "#8A9BB0", GLASS],
  ["team tag #9FF2FF on tag", "#9FF2FF", TAG_TEAM],
  ["GENERAL tag #C9D6E3 on tag", "#C9D6E3", TAG_GEN],
  ["row icon #7FE9FF on #0E1A26", "#7FE9FF", ROWICON],
  ["footer links #9FB3C8 on bg", "#9FB3C8", BG],
  ["dialog title #F2FBFF on dialog", "#F2FBFF", DIALOG],
  ["dialog label #C9D6E3 on dialog", "#C9D6E3", DIALOG],
  ["dialog input text #E8F6FF on input", "#E8F6FF", INPUT],
  ["dialog placeholder #7D8EA0 on input", "#7D8EA0", INPUT],
  ["dialog error #FF8A7A on dialog", "#FF8A7A", DIALOG],
  ["helper link #C9D6E3 on dialog", "#C9D6E3", DIALOG],
  ["helper steps #C9D6E3 on helper", "#C9D6E3", HELP],
  ["helper tip #8A9BB0 on helper", "#8A9BB0", HELP],
  ["Cancel #C9D6E3 on dialog", "#C9D6E3", DIALOG],
  ["error box #FF8A7A on glass", "#FF8A7A", GLASS],
  ["mobile manager #A9BACB on mobile glass", "#A9BACB", GLASS_M],
  ["mobile freshness #8A9BB0 on mobile glass", "#8A9BB0", GLASS_M],
  ["chat placeholder dt #8A9BB0 on glass", "#8A9BB0", GLASS],
];
const nonText = [
  ["focus ring #3BE8FF on bg (>= 3:1)", "#3BE8FF", BG, 3],
  ["focus ring #3BE8FF on glass (>= 3:1)", "#3BE8FF", GLASS, 3],
  ["input border #56687A on dialog (>= 3:1)", "#56687A", DIALOG, 3],
  ["dashed add border rgba(59,232,255,.45) composited on bg (>= 3:1)", null, BG, 3, over(hex("#3BE8FF"), 0.45, BG)],
];

let worst = Infinity;
let fails = 0;
for (const [name, fg, bg] of checks) {
  const r = ratio(hex(fg), bg);
  worst = Math.min(worst, r);
  const ok = r >= 4.5;
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"} ${r.toFixed(2)}:1  ${name}`);
}
for (const [name, fg, bg, min, rgb] of nonText) {
  const r = ratio(rgb ?? hex(fg), bg);
  const ok = r >= min;
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"} ${r.toFixed(2)}:1  ${name}`);
}
console.log(`\n${checks.length} text pairs, lowest ${worst.toFixed(2)}:1, ${fails} below threshold`);
process.exit(fails ? 1 : 0);
