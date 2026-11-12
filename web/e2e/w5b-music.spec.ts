import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { SHARED_USER, acquireUser, deleteUser, findTestUsers, userName } from "./clerk-users";
import { MUSIC_TRACKS } from "../lib/music-tracks";
import { sweepPage } from "../scripts/lib/sweep.mjs";
import { signIn, vis } from "./w4";
import { shot5, signOutViaMenu } from "./w5";

/** Prompt W5b PART 3: the About CTAs readable (computed colours) and the full contrast sweep of every page in both states;
 *  the site-wide music -- one audio element across Login -> Home -> Chat -> About -> Privacy -> Home, shuffle, mute, resume,
 *  the autoplay fallback, the button on every page at 1440 / 390 / 360 -- against the scratchpad backend (clerk mode, :8010,
 *  FPL budget 0) and the production build on :3002. Clerk test user w5bm (deleted at the end). Anthropic $0, FPL 0. */

test.describe.configure({ mode: "serial" });

const NAME = userName("w5bm"); // W10: E2E_SHARED_USER runs it on the run's one test user
let context: BrowserContext;
let page: Page;
const results: string[] = [];
const log = (s: string) => console.log(`[W5b] ${s}`);
const pass = (s: string) => {
  results.push(s);
  log(`PASS ${s}`);
};
const lowestSeen: { where: string; ratio: number; label: string }[] = [];

type AudioState = { present: boolean; paused: boolean; muted: boolean; src: string; t: number; volume: number; track: string; playing: string };
const audioState = (p: Page): Promise<AudioState> =>
  p.evaluate(() => {
    const a = document.querySelector('[data-testid="site-audio"]') as HTMLAudioElement | null;
    return { present: !!a, paused: a?.paused ?? true, muted: a?.muted ?? false, src: a?.getAttribute("src") ?? "", t: a?.currentTime ?? 0, volume: a?.volume ?? 0, track: a?.getAttribute("data-track") ?? "", playing: a?.getAttribute("data-playing") ?? "" };
  });

async function sweep(p: Page, where: string) {
  await p.waitForTimeout(400);
  const r = await sweepPage(p);
  if (r.lowest) lowestSeen.push({ where, ratio: r.lowest.ratio, label: r.lowest.label });
  log(`sweep ${where}: ${r.text.length} text controls, lowest ${r.lowest ? `${r.lowest.ratio.toFixed(2)}:1 ${r.lowest.label}` : "n/a"}, ${r.fails.length} below the bar`);
  expect(r.fails.map((f: { ratio: number; fg: string; bg: string; label: string }) => `${f.ratio}:1 ${f.fg} on ${f.bg} ${f.label}`), `contrast sweep ${where}`).toEqual([]);
  return r;
}

async function cta(p: Page) {
  return p.locator('[data-testid="hero-primary"]').evaluate((el) => {
    const cs = getComputedStyle(el);
    return { color: cs.color, bg: cs.backgroundColor, text: el.textContent?.trim() };
  });
}

test.beforeAll(async ({ browser }) => {
  if (!SHARED_USER) for (const id of await findTestUsers(NAME)) await deleteUser(id);
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
});

test.afterAll(async () => {
  if (!SHARED_USER) for (const id of await findTestUsers(NAME)) await deleteUser(id);
  const lowest = lowestSeen.reduce<{ where: string; ratio: number; label: string } | null>((m, r) => (m === null || r.ratio < m.ratio ? r : m), null);
  log(`SUMMARY lowest contrast across the sweep: ${lowest ? `${lowest.ratio.toFixed(2)}:1 ${lowest.label} on ${lowest.where}` : "n/a"} | clerk test users left ${(await findTestUsers(NAME)).length}`);
  for (const r of results) log(`RESULT ${r}`);
  await context?.close();
});

// ---- 1: the About CTAs + the contrast sweep, signed out then signed in ------------------------------------------------------------

test("1 About CTAs readable signed out and in; the computed-colour sweep of every page in both states", async () => {
  test.setTimeout(300_000);
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  const out = await cta(page);
  expect(out.color).toBe("rgb(2, 16, 22)");
  expect(out.bg).toBe("rgb(59, 232, 255)");
  await shot5(page, "w5b_about_cta_signed_out_after");
  await sweep(page, "/about signed out @1440");
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  await sweep(page, "/privacy signed out @1440");
  await page.goto("/login");
  await vis(page, "skip-intro").first().click();
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  await sweep(page, "/login @1440");

  await acquireUser(NAME);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  await expect(page.locator('[data-testid="home"]:visible')).toBeVisible({ timeout: 30_000 });
  await sweep(page, "/home signed in @1440");
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await sweep(page, "/chat signed in @1440");
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  const inn = await cta(page);
  expect(inn.text).toContain("Ask your first question");
  expect(inn.color).toBe("rgb(2, 16, 22)");
  expect(inn.bg).toBe("rgb(59, 232, 255)");
  const closing = await page.locator('[data-testid="closing-primary"]').evaluate((el) => getComputedStyle(el).color);
  expect(closing).toBe("rgb(2, 16, 22)");
  await shot5(page, "w5b_about_cta_signed_in_after");
  await page.locator('[data-testid="closing-primary"]').scrollIntoViewIfNeeded();
  await shot5(page, "w5b_about_closing_signed_in_after");
  await sweep(page, "/about signed in @1440");
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await sweep(page, "/privacy signed in @1440");
  // the phone size, signed in
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [url, ready] of [["/home", '[data-testid="home"]'], ["/chat", '[data-testid="chat"][data-ready="true"]'], ["/about", '[data-testid="about"][data-signed-in="true"]'], ["/privacy", '[data-testid="privacy"][data-signed-in="true"]']]) {
    await page.goto(url);
    await expect(page.locator(`${ready}:visible`)).toBeVisible({ timeout: 30_000 });
    await sweep(page, `${url} signed in @390`);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  pass("1 About CTAs #021016 on #3BE8FF signed out and in (hero + closing); the sweep passed on /login, /about, /privacy (out) and /home, /chat, /about, /privacy (in) at 1440 and 390");
});

// ---- 2: the same audio element across the site ----------------------------------------------------------------------------------

test("2 autoplay allowed: the music starts on Login and keeps playing across Home, Chat, About, Privacy, Home", async () => {
  test.setTimeout(300_000);
  await page.evaluate(() => {
    localStorage.setItem("fpl-sound", "1");
    sessionStorage.removeItem("fpl.music.resume");
  });
  await page.goto("/home");
  await signOutViaMenu(page); // a signed-in visit to /login goes to /home: start the journey signed out
  await page.goto("/login");
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  await expect(page.locator(".stage").first()).toHaveAttribute("data-music", "playing");
  // the intro's level (1.0) reached through the ~1.5 s fade-in
  await expect.poll(async () => (await audioState(page)).volume, { timeout: 8_000 }).toBeGreaterThan(0.35);
  await vis(page, "skip-intro").first().click();
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  await expect.poll(async () => (await audioState(page)).volume, { timeout: 5_000 }).toBeCloseTo(0.35, 2);
  const elementId = await page.evaluate(() => {
    const a = document.querySelector('[data-testid="site-audio"]') as HTMLAudioElement;
    (a as unknown as { __w5b: number }).__w5b = Math.random();
    return (a as unknown as { __w5b: number }).__w5b;
  });
  // sign in by email code: a client-side navigation to /home
  await page.locator("#c-email").fill(`${NAME}+clerk_test@example.com`);
  await page.getByTestId("send-code").click();
  await expect(page.getByTestId("code-sent-title")).toHaveText("Check your email");
  await page.getByTestId("otp").fill("424242");
  await page.waitForURL("**/home", { timeout: 30_000 });
  const steps: [string, () => Promise<unknown>][] = [
    ["/chat", () => vis(page, "choice-general").first().click()],
    ["/home", () => vis(page, "back-home").first().click()],
    ["/about", () => page.locator('.hm-foot a[href="/about"]:visible').first().click()],
    ["/privacy", () => page.locator('[data-testid="public-footer"] a[href="/privacy"]:visible').first().click()],
    ["/home", () => vis(page, "header-home").first().click()],
  ];
  let last = await audioState(page);
  const track = last.track;
  for (const [url, go] of steps) {
    await go();
    await page.waitForURL(`**${url}**`, { timeout: 30_000 });
    await page.waitForTimeout(1500);
    const now = await audioState(page);
    const same = await page.evaluate(() => (document.querySelector('[data-testid="site-audio"]') as unknown as { __w5b?: number })?.__w5b);
    expect(same, `${url}: the SAME audio element`).toBe(elementId);
    expect(now.paused, `${url}: still playing`).toBe(false);
    expect(now.track, `${url}: the same track`).toBe(track);
    expect(now.t, `${url}: currentTime moved forward (${last.t} -> ${now.t})`).toBeGreaterThan(last.t);
    log(`${url}: t=${now.t.toFixed(1)} s, track ${now.track}`);
    last = now;
  }
  pass(`2 one audio element (same object) through Login -> Home -> Chat -> About -> Privacy -> Home; currentTime only forward (${last.t.toFixed(1)} s), track ${track} unchanged`);
});

// ---- 3: shuffle --------------------------------------------------------------------------------------------------------------

test("3 shuffle: 20 visits never start on the previous visit's track; 25 'ended' play every track before any repeat", async () => {
  test.setTimeout(300_000);
  // a "visit" = a fresh tab with no sessionStorage resume entry (a reload of the SAME tab is a resume, not a visit; and a
  // goto in the same tab writes the resume entry on pagehide first, so the old same-tab loop measured the resume path)
  const starts: string[] = [];
  for (let i = 0; i < 20; i++) {
    const tab = await context.newPage();
    await tab.addInitScript(() => {
      try {
        sessionStorage.removeItem("fpl.music.resume");
      } catch {
        /* no storage */
      }
    });
    await tab.goto("/about");
    await expect.poll(async () => (await audioState(tab)).track, { timeout: 10_000 }).toMatch(/\.mp3$/);
    const t = (await audioState(tab)).track;
    const last = await tab.evaluate(() => localStorage.getItem("fpl.music.last"));
    expect(last, `visit ${i + 1}: the start is remembered`).toBe(t);
    starts.push(t);
    await tab.close();
  }
  log(`3 starts: ${starts.join(" > ")}`);
  for (let i = 1; i < starts.length; i++) expect(starts[i], `visit ${i + 1} vs ${i}`).not.toBe(starts[i - 1]);
  const distinct = new Set(starts).size;
  // the queue: fire "ended" 25 times
  const played: string[] = [await audioState(page).then((a) => a.track)];
  for (let i = 0; i < 25; i++) {
    await page.evaluate(() => (document.querySelector('[data-testid="site-audio"]') as HTMLAudioElement).dispatchEvent(new Event("ended")));
    await expect.poll(async () => (await audioState(page)).track, { timeout: 5_000 }).not.toBe(played[played.length - 1]);
    played.push((await audioState(page)).track);
  }
  const n = MUSIC_TRACKS.length;
  const firstCycle = played.slice(0, n);
  expect(new Set(firstCycle).size, "the first 10 played are all 10 tracks").toBe(n);
  const second = played.slice(n, 2 * n);
  expect(new Set(second).size, "the second 10 again all 10").toBe(n);
  for (let i = 1; i < played.length; i++) expect(played[i], `no back-to-back repeat at ${i}`).not.toBe(played[i - 1]);
  pass(`3 shuffle: 20 visits, ${distinct} distinct starts, no visit on the previous start; 26 plays over 25 'ended': both 10-track cycles complete, no back-to-back repeat`);
});

// ---- 4: mute -----------------------------------------------------------------------------------------------------------------

test("4 mute on Chat: paused, no audio request while muted, stays muted across navigation and a reload; unmute resumes", async () => {
  test.setTimeout(300_000);
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  const before = await audioState(page);
  await vis(page, "sound-toggle").click();
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-pressed", "true");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-label", "Play music");
  const muted = await audioState(page);
  expect(muted.paused).toBe(true);
  expect(muted.src, "the source is dropped while muted").toBe("");
  expect(await page.evaluate(() => localStorage.getItem("fpl-sound"))).toBe("0");
  let audioRequests = 0;
  const onReq = (req: { url: () => string }) => {
    if (/\/music\/.*\.mp3/.test(req.url())) audioRequests++;
  };
  page.on("request", onReq);
  await page.waitForTimeout(4000);
  // Chat has no About link: Chat -> Home (the header's Home) -> About (Home's footer), both client-side
  await page.locator("a.ch-home:visible").first().click();
  await expect(page.locator('[data-testid="home"]:visible').first()).toBeVisible({ timeout: 20_000 });
  expect((await audioState(page)).paused, "still muted after a navigation to Home").toBe(true);
  await page.locator('.hm-foot a[href="/about"]:visible').first().click();
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(2000);
  expect((await audioState(page)).paused, "still muted after a navigation").toBe(true);
  await page.reload();
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(2000);
  expect((await audioState(page)).paused, "still muted after a reload").toBe(true);
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-pressed", "true");
  page.off("request", onReq);
  expect(audioRequests, "no audio request while muted").toBe(0);
  await vis(page, "sound-toggle").click();
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-pressed", "false");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-label", "Mute music");
  const resumed = await audioState(page);
  expect(resumed.track).toBe(before.track);
  expect(Math.abs(resumed.t - before.t)).toBeLessThan(8);
  expect(await page.evaluate(() => localStorage.getItem("fpl-sound"))).toBe("1");
  pass(`4 mute: paused + source dropped, 0 audio requests over ~8 s, muted across a navigation and a reload; unmute resumed ${before.track} near ${before.t.toFixed(1)} s`);
});

// ---- 5: reload resume; the default autoplay policy --------------------------------------------------------------------------------

test("5 reload while playing -> the same track within ±2 s; default autoplay policy -> silent until the first click", async ({ browser }) => {
  test.setTimeout(300_000);
  await page.goto("/privacy");
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  await page.waitForTimeout(4000); // past a save tick
  const before = await audioState(page);
  await page.reload();
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  const after = await audioState(page);
  expect(after.track).toBe(before.track);
  expect(Math.abs(after.t - before.t), `resumed ${before.t.toFixed(1)} -> ${after.t.toFixed(1)}`).toBeLessThanOrEqual(2 + 1.5);
  // the default policy, reproduced as e2e/login-flow.spec.ts does: Playwright-driven pages carry a user activation from the
  // start, so neither a policy flag (tried: --autoplay-policy=document-user-activation-required still played) nor
  // navigator.userActivation reproduces a cold visitor; play() is refused (NotAllowedError) until a real gesture
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p2 = await ctx.newPage();
  await p2.addInitScript(() => {
    let gesture = false;
    for (const ev of ["pointerdown", "keydown", "touchstart"]) window.addEventListener(ev, () => (gesture = true), { capture: true });
    const original = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function play(this: HTMLMediaElement) {
      if (!gesture) return Promise.reject(new DOMException("autoplay blocked (test policy)", "NotAllowedError"));
      return original.call(this);
    };
  });
  const errors: string[] = [];
  p2.on("pageerror", (e) => errors.push(e.message));
  p2.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await p2.goto("/about");
  await expect(p2.locator('[data-testid="about"]')).toBeVisible({ timeout: 20_000 });
  await p2.waitForTimeout(2500);
  const blocked = await audioState(p2);
  expect(blocked.paused, "silent while autoplay is blocked").toBe(true);
  await expect(p2.locator('[data-testid="confirm-dialog"], [role="dialog"]')).toHaveCount(0);
  await p2.mouse.click(700, 500);
  await expect.poll(async () => (await audioState(p2)).paused, { timeout: 10_000 }).toBe(false);
  expect(errors.filter((e) => /NotAllowedError|play\(\)/.test(e)), "no error surfaced").toEqual([]);
  await ctx.close();
  pass(`5 reload resumed ${before.track} at ${before.t.toFixed(1)} -> ${after.t.toFixed(1)} s; default policy: silent, then playing on the first click, no error`);
});

// ---- 6: the button on every page, keyboard, labels, tooltip, axe ------------------------------------------------------------------------

test("6 the button on every page at 1440 / 390 / 360, keyboard, label + aria-pressed, tooltip, axe", async () => {
  test.setTimeout(300_000);
  const pages: [string, string][] = [["/home", '[data-testid="home"]'], ["/chat", '[data-testid="chat"][data-ready="true"]'], ["/about", '[data-testid="about"][data-signed-in="true"]'], ["/privacy", '[data-testid="privacy"][data-signed-in="true"]']];
  for (const [w, h] of [[1440, 900], [390, 844], [360, 740]]) {
    await page.setViewportSize({ width: w, height: h });
    for (const [url, ready] of pages) {
      await page.goto(url);
      await expect(page.locator(`${ready}:visible`)).toBeVisible({ timeout: 30_000 });
      const btn = vis(page, "sound-toggle");
      await expect(btn).toBeVisible();
      const b = (await btn.boundingBox())!;
      expect(Math.round(b.width), `${url} @${w}: width`).toBeGreaterThanOrEqual(w >= 981 ? 40 : 44);
      expect(Math.round(b.height)).toBeGreaterThanOrEqual(w >= 981 ? 40 : 44);
      expect(b.x + b.width, `${url} @${w}: inside the viewport`).toBeLessThanOrEqual(w + 1);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${url} @${w}: no horizontal overflow`).toBeLessThanOrEqual(1);
      const title = await btn.getAttribute("title");
      expect(title).toMatch(/^Now playing: .+ — .+$/);
      if (w === 1440 || w === 390) await shot5(page, `w5b_mute_${url.replace("/", "")}`);
      log(`${url} @${w}x${h}: ${Math.round(b.width)}x${Math.round(b.height)} at x=${Math.round(b.x)}, "${title}"`);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  // keyboard: Tab to the button, Enter mutes (label + aria-pressed switch), Space plays again
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  await page.keyboard.press("Tab");
  for (let i = 0; i < 10; i++) {
    const tid = await page.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute("data-testid"));
    if (tid === "sound-toggle") break;
    await page.keyboard.press("Tab");
  }
  expect(await page.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute("data-testid"))).toBe("sound-toggle");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-label", "Mute music");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Enter");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-pressed", "true");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-label", "Play music");
  expect((await audioState(page)).paused).toBe(true);
  await page.keyboard.press("Space");
  await expect(vis(page, "sound-toggle")).toHaveAttribute("aria-pressed", "false");
  await expect.poll(async () => (await audioState(page)).paused, { timeout: 10_000 }).toBe(false);
  // the login page's control, same component -- in a signed-out context (a signed-in visit to /login goes to /home)
  const out = await page.context().browser()!.newContext({ viewport: { width: 1440, height: 900 } });
  const lp = await out.newPage();
  await lp.goto("/login");
  await vis(lp, "skip-intro").first().click();
  await expect(lp.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  await expect(vis(lp, "sound-toggle")).toBeVisible();
  const lb = (await vis(lp, "sound-toggle").boundingBox())!;
  expect(Math.round(lb.width), "/login @1440: width").toBeGreaterThanOrEqual(40);
  expect(await vis(lp, "sound-toggle").getAttribute("title")).toMatch(/^Now playing: .+ — .+$/);
  await shot5(lp, "w5b_mute_login");
  await lp.setViewportSize({ width: 390, height: 844 });
  const lb2 = (await vis(lp, "sound-toggle").boundingBox())!;
  expect(Math.round(lb2.width), "/login @390: width").toBeGreaterThanOrEqual(44);
  expect(lb2.x + lb2.width, "/login @390: inside the viewport").toBeLessThanOrEqual(391);
  await shot5(lp, "w5b_mute_login");
  log(`/login: ${Math.round(lb.width)}x${Math.round(lb.height)} @1440, ${Math.round(lb2.width)}x${Math.round(lb2.height)} @390`);
  await out.close();
  // axe on each page with the button
  for (const [url, ready] of [["/home", '[data-testid="home"]:not([data-state="loading"])'], ["/about", '[data-testid="about"][data-signed-in="true"]'], ["/privacy", '[data-testid="privacy"][data-signed-in="true"]']]) {
    await page.goto(url);
    await expect(page.locator(`${ready}:visible`)).toBeVisible({ timeout: 30_000 });
    const r = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`), `axe ${url}`).toEqual([]);
    log(`axe ${url}: 0 serious/critical, ${r.violations.length - bad.length} other`);
  }
  pass("6 the button on Home, Chat, About, Privacy and Login at 1440 (40px), 390 and 360 (44px, no overflow); Tab + Enter / Space toggle; labels Mute music / Play music + aria-pressed; tooltip 'Now playing: title — artist'; axe 0 serious/critical");
});
