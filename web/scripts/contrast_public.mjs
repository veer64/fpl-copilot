// Prompt W5: the About / Privacy pages' and the delete dialogs' text / background pairs (app/public-pages.css, home.css W5
// section + the references) at >= 4.5:1. Run: node scripts/contrast_public.mjs
//
// Prompt W5b: this static table lists the DESIGN's pairs (#021016 on #3BE8FF for the primary button) and so could not see the
// cascade accident that painted the About CTAs cyan on cyan (`.pp a` outranking `.pp-btn-p`). `--live <baseURL>` adds the
// computed-colour sweep (scripts/lib/sweep.mjs): every button and button-styled link on /login, /about and /privacy, signed
// out, desktop 1440 and phone 390, as the browser painted them -- that case fails here. The signed-in pages are swept by
// e2e/w5b-music.spec.ts with the same function. Run: node scripts/contrast_public.mjs --live http://localhost:3002
//
// Prompt W6: `--storage <state.json>` (a Playwright storageState of a signed-in ADMIN session, as e2e/w6-admin.spec.ts saves
// one) adds /admin to the live sweep at both widths: the page needs the owner's session, so the signed-out run cannot see it.
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
const GLASS = over("#080F18", 0.8, BG);
const DLG = over("#070D14", 0.98, BG);
const MENU = over("#080F18", 0.96, BG);
const SHEET = "#07101A";
const pairs = [
  ["hero sub #C9D6E3 on the page", "#C9D6E3", BG],
  ["h1 / h2 #F2FBFF on the page", "#F2FBFF", BG],
  ["eyebrow #7FE9FF on the page", "#7FE9FF", BG],
  ["tile text #A9BACB on glass", "#A9BACB", GLASS],
  ["tile title #F2FBFF on glass", "#F2FBFF", GLASS],
  ["chip text #E8F6FF on the chip", "#E8F6FF", over("#080F18", 0.8, GLASS)],
  ["fine print #A9BACB on glass", "#A9BACB", GLASS],
  ["fine print eyebrow #FFC23D on glass", "#FFC23D", GLASS],
  ["made-by sub #A9BACB on glass", "#A9BACB", GLASS],
  ["link button #E8F6FF on its tint", "#E8F6FF", over("#080F18", 0.7, GLASS)],
  ["footer label #6E8093 on the page", "#6E8093", BG],
  ["footer nav #A9BACB on the page", "#A9BACB", BG],
  ["primary button #021016 on #3BE8FF", "#021016", "#3BE8FF"],
  ["secondary button #E8F6FF on its tint", "#E8F6FF", over("#FFFFFF", 0.03, BG)],
  ["header Home #C9D6E3 on its tint", "#C9D6E3", over("#080F18", 0.6, over("#04070C", 0.85, BG))],
  ["example table header #8A9BB0 on #0B1520", "#8A9BB0", "#0B1520"],
  ["example body #DDE8F2 on glass", "#DDE8F2", GLASS],
  ["example cyan 3BE8FF on its tint", "#3BE8FF", over("#3BE8FF", 0.06, GLASS)],
  ["source chip #C9D6E3 on glass", "#C9D6E3", GLASS],
  ["tag #9FF2FF on its tint", "#9FF2FF", over("#3BE8FF", 0.1, GLASS)],
  ["privacy pill #C9D6E3 on the page", "#C9D6E3", BG],
  ["toc link #A9BACB on the page", "#A9BACB", BG],
  ["toc number #6E8093 on the page", "#6E8093", BG],
  ["toc current #F2FBFF on its tint", "#F2FBFF", over("#3BE8FF", 0.08, BG)],
  ["toc label #6E8093 on the page", "#6E8093", BG],
  ["section number #7FE9FF on the page", "#7FE9FF", BG],
  ["row title #F2FBFF on glass", "#F2FBFF", GLASS],
  ["row text #A9BACB on glass", "#A9BACB", GLASS],
  ["provider text #A9BACB on glass", "#A9BACB", GLASS],
  ["danger text #A9BACB on the danger card", "#A9BACB", over("#E5484D", 0.07, over("#080F18", 0.85, BG))],
  ["danger strong #FF8A8E on the danger card", "#FF8A8E", over("#E5484D", 0.07, over("#080F18", 0.85, BG))],
  ["danger mail #8A9BB0 on the danger card", "#8A9BB0", over("#E5484D", 0.07, over("#080F18", 0.85, BG))],
  ["contact cyan #7FE9FF on glass", "#7FE9FF", GLASS],
  ["chipnav text #C9D6E3 on its tint", "#C9D6E3", over("#080F18", 0.7, BG)],
  ["menu: Sign out #FF8A7A on the menu", "#FF8A7A", MENU],
  ["menu: Delete account #FF6B6B on the menu", "#FF6B6B", MENU],
  ["menu: owner note #8A9BB0 on the menu", "#8A9BB0", MENU],
  ["menu: email #A9BACB on the menu", "#A9BACB", MENU],
  ["dialog title #F2FBFF on the dialog", "#F2FBFF", DLG],
  ["dialog intro #A9BACB on the dialog", "#A9BACB", DLG],
  ["dialog list #E8F6FF on its box", "#E8F6FF", over("#FFFFFF", 0.03, DLG)],
  ["dialog warning #FF8A7A on the dialog", "#FF8A7A", DLG],
  ["dialog alert #FFC2B8 on its tint", "#FFC2B8", over("#FF8A7A", 0.1, DLG)],
  ["dialog alert link #FFD9D2 on its tint", "#FFD9D2", over("#FF8A7A", 0.1, DLG)],
  ["cancel #E8F6FF on its tint", "#E8F6FF", over("#FFFFFF", 0.03, DLG)],
  ["red button #FFFFFF on #C8484D (the reference's #E5484D is 3.94:1)", "#FFFFFF", "#C8484D"],
  ["red button hover #FFFFFF on #B93F44", "#FFFFFF", "#B93F44"],
  ["sheet title #F2FBFF on the sheet", "#F2FBFF", SHEET],
  ["sheet intro #A9BACB on the sheet", "#A9BACB", SHEET],
  ["login deleted note #B8F5D8 on its tint", "#B8F5D8", over("#5BE3A4", 0.1, BG)],
  ["disabled menu item #5E4548 on the menu (disabled: exempt, listed only)", "#5E4548", MENU],
];
let worst = 99;
let fails = 0;
for (const [name, fg, bg] of pairs) {
  const r = ratio(fg, bg);
  const exempt = name.includes("exempt");
  if (!exempt) worst = Math.min(worst, r);
  const ok = exempt || r >= 4.5;
  if (!ok) fails++;
  console.log(`${ok ? "ok  " : "FAIL"} ${r.toFixed(2)}:1  ${name}`);
}
console.log(`\n${pairs.length} pairs, lowest (non-exempt) ${worst.toFixed(2)}:1, ${fails} below 4.5:1`);
// --selftest: the W5b cascade on a fixture (the page-wide link colour outranking the button class) MUST fail the sweep
if (process.argv.includes("--selftest")) {
  const { chromium } = await import("playwright");
  const { sweepPage } = await import("./lib/sweep.mjs");
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
  await page.setContent(`<style>body{background:#04070C}.pp a{color:#7FE9FF}.pp-btn-p{background:#3BE8FF;color:#021016;padding:8px 16px;display:inline-flex}</style>
    <div class="pp"><a href="/home" class="pp-btn-p">Ask your first question</a></div>`);
  const r = await sweepPage(page);
  await browser.close();
  const f = r.fails[0];
  console.log(`selftest (the W5b cascade on a fixture): ${f ? "FAILS as it must -- " + f.ratio.toFixed(2) + ":1 " + f.fg + " on " + f.bg : "NOT caught"}`);
  process.exit(f ? 0 : 1);
}

// --live <baseURL>: the computed-colour sweep of the signed-out pages (scripts/lib/sweep.mjs)
const liveAt = process.argv.indexOf("--live");
if (liveAt < 0) process.exit(fails ? 1 : 0);
const base = (process.argv[liveAt + 1] || "http://localhost:3002").replace(/\/$/, "");
const { chromium } = await import("playwright");
const { sweepPage } = await import("./lib/sweep.mjs");
const browser = await chromium.launch({ channel: "msedge", headless: true });
let liveFails = 0;
let liveLowest = null;
for (const [w, h] of [[1440, 900], [390, 844]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  for (const path of ["/login", "/about", "/privacy"]) {
    await page.goto(base + path, { waitUntil: "networkidle" });
    if (path === "/login") {
      await page.getByTestId("skip-intro").click().catch(() => undefined);
      await page.waitForSelector('.stage[data-phase="login"]', { timeout: 15000 }).catch(() => undefined);
    }
    await page.waitForTimeout(500);
    const r = await sweepPage(page);
    liveFails += r.fails.length;
    if (r.lowest && (liveLowest === null || r.lowest.ratio < liveLowest.ratio)) liveLowest = { ...r.lowest, where: `${path} @${w}` };
    console.log(`live ${path} @${w}x${h}: ${r.text.length} text controls, lowest ${r.lowest ? r.lowest.ratio.toFixed(2) + ":1 " + r.lowest.label : "n/a"}, ${r.fails.length} below the bar`);
    for (const f of r.fails) console.log(`  FAIL ${f.ratio.toFixed(2)}:1  ${f.fg} on ${f.bg}  ${f.label}${f.note ? "  (" + f.note + ")" : ""}`);
  }
  await page.close();
}
// Prompt W6: /admin with a signed-in admin session (--storage <state.json>)
const storageAt = process.argv.indexOf("--storage");
if (storageAt > 0 && process.argv[storageAt + 1]) {
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const ctx = await browser.newContext({ storageState: process.argv[storageAt + 1], viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    await page.goto(base + "/admin", { waitUntil: "networkidle" });
    const ready = await page.waitForSelector('[data-testid="admin"][data-state="ready"]', { timeout: 30000 }).then(() => true).catch(() => false);
    if (!ready) {
      console.log(`live /admin @${w}x${h}: NOT READY (no admin session in the storage state, or the API refused) -- counted as a failure`);
      liveFails += 1;
    } else {
      await page.waitForTimeout(500);
      const r = await sweepPage(page);
      liveFails += r.fails.length;
      if (r.lowest && (liveLowest === null || r.lowest.ratio < liveLowest.ratio)) liveLowest = { ...r.lowest, where: `/admin @${w}` };
      console.log(`live /admin @${w}x${h} (signed in): ${r.text.length} text controls, lowest ${r.lowest ? r.lowest.ratio.toFixed(2) + ":1 " + r.lowest.label : "n/a"}, ${r.fails.length} below the bar`);
      for (const f of r.fails) console.log(`  FAIL ${f.ratio.toFixed(2)}:1  ${f.fg} on ${f.bg}  ${f.label}${f.note ? "  (" + f.note + ")" : ""}`);
    }
    await ctx.close();
  }
}
await browser.close();
console.log(`live sweep (signed out${storageAt > 0 ? " + /admin signed in" : ""}): ${liveFails} failures, lowest ${liveLowest ? liveLowest.ratio.toFixed(2) + ":1 " + liveLowest.label + " on " + liveLowest.where : "n/a"}`);
process.exit(fails || liveFails ? 1 : 0);
