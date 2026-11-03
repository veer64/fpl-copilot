import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** Prompt W1 Part 5 (revised 2 Nov 2026, gate removed): the intro auto-starts and reaches login in <= 7 s, Skip and Esc,
 *  the song starts on the first interaction (from 0 s) and never auto-starts with a remembered sound-off, reduced motion,
 *  the missing-image fallback, keyboard order and the screenshots. Desktop (1440x900) and mobile (390x844) projects. */

const SHOTS = process.env.W1_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w1_login_files");

function shotName(page: Page, name: string) {
  const vp = page.viewportSize()!;
  return path.join(SHOTS, `${name}_${vp.width}x${vp.height}.png`);
}

const stage = (page: Page) => page.locator(".stage");
const audio = (page: Page) =>
  page.evaluate(() => {
    const a = document.querySelector("audio")!;
    return { paused: a.paused, t: a.currentTime, volume: a.volume, muted: a.muted };
  });
const centre = (page: Page) => {
  const vp = page.viewportSize()!;
  return { x: Math.round(vp.width * 0.5), y: Math.round(vp.height * 0.55) };
};
/** the intro's start is stamped on the stage (performance.now()) by the page itself */
const introStarted = (page: Page) => page.waitForSelector(".stage[data-intro-started]", { timeout: 15_000 });
const soundOff = (page: Page) =>
  page.addInitScript(() => {
    try {
      localStorage.setItem("fpl-sound", "0");
    } catch {}
  });

test.beforeAll(() => {
  fs.mkdirSync(SHOTS, { recursive: true });
});

test("A2: the intro starts by itself and reaches login within 7 s, with screenshots", async ({ page }) => {
  await page.addInitScript(() => {
    const marks: Record<string, number> = {};
    (window as unknown as { __phaseMarks: Record<string, number> }).__phaseMarks = marks;
    const obs = new MutationObserver(() => {
      const p = document.querySelector(".stage")?.getAttribute("data-phase");
      if (p && !(p in marks)) marks[p] = performance.now();
    });
    document.addEventListener("DOMContentLoaded", () =>
      obs.observe(document.documentElement, { attributes: true, subtree: true, attributeFilter: ["data-phase"] }),
    );
  });
  await page.goto("/login");
  await expect(stage(page)).toHaveAttribute("data-phase", "intro");
  await expect(page.getByTestId("hud")).toBeVisible();
  await expect(page.getByTestId("tap-for-sound")).toBeVisible();
  await expect(page.getByTestId("skip-intro")).toBeVisible();
  await introStarted(page);
  const t0 = Date.now();
  await page.waitForTimeout(Math.max(0, 1000 - (Date.now() - t0)));
  await page.screenshot({ path: shotName(page, "intro_1.0s") });
  await page.waitForTimeout(Math.max(0, 4000 - (Date.now() - t0)));
  await page.screenshot({ path: shotName(page, "intro_4.0s") });

  await expect(stage(page)).toHaveAttribute("data-phase", "login", { timeout: 8000 });
  const wall = Date.now() - t0;
  const { started, loginAt } = await page.evaluate(() => ({
    started: Number(document.querySelector(".stage")!.getAttribute("data-intro-started")),
    loginAt: (window as unknown as { __phaseMarks: Record<string, number> }).__phaseMarks.login,
  }));
  const introMs = Math.round(loginAt - started);
  expect(introMs).toBeGreaterThan(6100);
  expect(introMs).toBeLessThan(7000);
  expect(wall).toBeLessThan(7000 + 1500); // the wall clock also carries two screenshot captures
  await expect(page.getByTestId("sign-in-card")).toBeVisible();
  await page.waitForTimeout(1200); // let the rise animations finish before the screenshot
  await page.screenshot({ path: shotName(page, "login") });
  console.log(`A2 intro -> login: ${introMs} ms in-page (wall clock from the intro's start, with screenshots: ${wall} ms)`);
});

test("protected: /teams signed-out ends on /login", async ({ page }) => {
  await page.goto("/teams");
  await page.waitForURL("**/login**", { timeout: 15_000 });
  await expect(stage(page)).toHaveAttribute("data-phase", /intro|login/);
});

test("A2: Skip intro, and Esc, go straight to login", async ({ page }) => {
  await page.goto("/login");
  await expect(stage(page)).toHaveAttribute("data-phase", "intro");
  await page.getByTestId("skip-intro").click();
  await expect(stage(page)).toHaveAttribute("data-phase", "login");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Every decision");

  await page.goto("/login");
  await expect(stage(page)).toHaveAttribute("data-phase", "intro");
  await page.keyboard.press("Escape");
  await expect(stage(page)).toHaveAttribute("data-phase", "login");
});

test("audio: the first click anywhere starts the song from 0 s at intro volume; it ducks to 35 % on login", async ({ page }) => {
  await page.goto("/login");
  await introStarted(page);
  expect((await audio(page)).paused).toBe(true);
  const { x, y } = centre(page);
  await page.mouse.click(x, y); // nothing clickable there: just the first interaction
  await expect.poll(async () => (await audio(page)).paused, { timeout: 5000 }).toBe(false);
  const a1 = await audio(page);
  expect(a1.t).toBeLessThan(1.5); // from the very beginning (AUDIO_START_OFFSET = 0)
  expect(a1.volume).toBe(1);
  expect(a1.muted).toBe(false);
  await expect(page.getByTestId("tap-for-sound")).toHaveCount(0); // the pill hides once the song plays
  await expect(stage(page)).toHaveAttribute("data-music", "playing");
  await expect(stage(page)).toHaveAttribute("data-phase", "login", { timeout: 8000 });
  expect((await audio(page)).volume).toBeCloseTo(0.35, 2);
  expect((await audio(page)).paused).toBe(false);
  console.log(`audio started at t=${a1.t.toFixed(3)} s, volume ${a1.volume} -> ${(await audio(page)).volume} on login`);
});

test("audio: the Tap for sound pill starts the song and hides", async ({ page }) => {
  await page.goto("/login");
  await introStarted(page);
  await page.getByTestId("tap-for-sound").click();
  await expect.poll(async () => (await audio(page)).paused, { timeout: 5000 }).toBe(false);
  expect((await audio(page)).t).toBeLessThan(1.5);
  await expect(page.getByTestId("tap-for-sound")).toHaveCount(0);
});

test("audio: a remembered sound-off never auto-starts the song; the toggle starts it later at 35 %", async ({ page }) => {
  await soundOff(page);
  await page.goto("/login");
  await introStarted(page);
  const { x, y } = centre(page);
  await page.mouse.click(x, y);
  await page.keyboard.press("Shift");
  await page.waitForTimeout(800);
  expect((await audio(page)).paused).toBe(true);
  await expect(page.getByTestId("tap-for-sound")).toBeVisible(); // still offered: an explicit tap would override "off"
  await page.getByTestId("skip-intro").click();
  await expect(stage(page)).toHaveAttribute("data-phase", "login");
  const toggle = page.getByTestId("sound-toggle");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect((await audio(page)).paused).toBe(true);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => (await audio(page)).paused, { timeout: 5000 }).toBe(false);
  expect((await audio(page)).volume).toBeCloseTo(0.35, 2);
  expect(await page.evaluate(() => localStorage.getItem("fpl-sound"))).toBe("1");
});

test("A5: reduced motion shows the login state at once, with no running animations", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto("/login");
  await expect(stage(page)).toHaveAttribute("data-phase", "login");
  await expect(page.getByTestId("hud")).toHaveCount(0);
  const running = await page.evaluate(() =>
    document.getAnimations().filter((a) => a.playState === "running" && a instanceof CSSAnimation).length,
  );
  expect(running).toBe(0);
  const tiltTransform = await page.locator(".pl-v .tilt").evaluate((el) => getComputedStyle(el).transform);
  expect(tiltTransform).toBe("none");
  await context.close();
});

test("A5: a failed player image falls back to the SVG figures", async ({ page }) => {
  await page.route("**/players/vandijk-body.webp", (route) => route.abort());
  await page.goto("/login");
  await page.getByTestId("skip-intro").click();
  await expect(page.locator(".ath")).toHaveCount(2);
  await expect(page.locator(".pl")).toHaveCount(0);
  await expect(page.locator(".tag")).toHaveCount(2);
});

test("A6: keyboard-only order reaches every control with visible focus", async ({ page }) => {
  await soundOff(page); // so a Tab is not also the first interaction that starts the song and hides the pill
  await page.goto("/login");
  await introStarted(page);
  const focusInfo = () =>
    page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      if (el.tagName === "NEXTJS-PORTAL") return { id: "nextjs-portal (dev overlay, skipped)", ring: true, outline: "" };
      const cs = getComputedStyle(el);
      const ring = el.matches(":focus-visible") && cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2;
      return { id: el.getAttribute("data-testid") || el.id || el.textContent?.trim().slice(0, 24) || el.tagName, ring, outline: cs.outlineColor };
    });
  // the intro: Tap for sound, then Skip intro
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("tap-for-sound")).toBeFocused();
  expect((await focusInfo())?.ring).toBe(true);
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("skip-intro")).toBeFocused();
  expect((await focusInfo())?.ring).toBe(true);
  await page.keyboard.press("Enter"); // Skip -> login
  await expect(stage(page)).toHaveAttribute("data-phase", "login");
  // entering the login state parks focus on the card (so Tab reaches Continue with Google first); Shift+Tab from there
  // reaches the header's sound toggle, and the forward order is walked from that toggle. The card's controls are disabled
  // until Clerk has loaded (a moment after a Skip), so wait for that first.
  await expect(page.getByTestId("sign-in-card")).toBeFocused();
  await expect(page.getByTestId("google")).toBeEnabled({ timeout: 15_000 });
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByTestId("sound-toggle")).toBeFocused();

  const seen: string[] = [];
  for (let i = 0; i < 12; i++) {
    if (i > 0) await page.keyboard.press("Tab");
    const info = await focusInfo();
    if (!info) break;
    seen.push(`${info.id}${info.ring ? "" : " (NO RING)"}`);
    if (!info.ring) throw new Error(`no visible focus ring on ${info.id} (outline ${info.outline})`);
  }
  console.log(`A6 tab order: tap-for-sound -> skip-intro -> [login] ${seen.join(" -> ")}`);
  for (const must of ["sound-toggle", "google", "c-email", "send-code", "Privacy", "About"]) {
    expect(seen.some((s) => s.startsWith(must))).toBe(true);
  }
});
