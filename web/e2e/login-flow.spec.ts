import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** Prompt W1 Part 5: the gate -> intro -> login flow, Skip, Esc, reduced motion, the missing-image fallback, keyboard
 *  order and the screenshots. Runs on the desktop (1440x900) and mobile (390x844) projects. */

const SHOTS = process.env.W1_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w1_login_files");

function shotName(page: Page, name: string) {
  const vp = page.viewportSize()!;
  return path.join(SHOTS, `${name}_${vp.width}x${vp.height}.png`);
}

test.beforeAll(() => {
  fs.mkdirSync(SHOTS, { recursive: true });
});

test("A2: gate -> Kick off -> intro -> login within 7 s, with screenshots", async ({ page }) => {
  // the intro's length is measured in-page (performance.now at each phase change): the wall clock below also carries the
  // screenshot captures, which stall the renderer
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
  const stage = page.locator(".stage");
  await expect(stage).toHaveAttribute("data-phase", "gate");
  await expect(page.getByTestId("kick-off")).toBeVisible();
  await page.screenshot({ path: shotName(page, "gate") });

  const t0 = Date.now();
  await page.getByTestId("kick-off").click();
  await expect(stage).toHaveAttribute("data-phase", "intro");
  await expect(page.getByTestId("hud")).toBeVisible();
  await page.waitForTimeout(Math.max(0, 1000 - (Date.now() - t0)));
  await page.screenshot({ path: shotName(page, "intro_1.0s") });
  await page.waitForTimeout(Math.max(0, 4000 - (Date.now() - t0)));
  await page.screenshot({ path: shotName(page, "intro_4.0s") });

  await expect(stage).toHaveAttribute("data-phase", "login", { timeout: 8000 });
  const wall = Date.now() - t0;
  const marks = await page.evaluate(() => (window as unknown as { __phaseMarks: Record<string, number> }).__phaseMarks);
  const introMs = Math.round(marks.login - marks.intro);
  expect(introMs).toBeGreaterThan(6100);
  expect(introMs).toBeLessThan(7000);
  await expect(page.getByTestId("sign-in-card")).toBeVisible();
  await page.waitForTimeout(1200); // let the rise animations finish before the screenshot
  await page.screenshot({ path: shotName(page, "login") });
  console.log(`A2 intro -> login: ${introMs} ms in-page (wall clock from the click, with screenshots: ${wall} ms)`);
});

test("protected: /teams signed-out ends on /login", async ({ page }) => {
  await page.goto("/teams");
  await page.waitForURL("**/login**", { timeout: 15_000 });
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "gate");
});

test("A2: Skip intro on the gate goes straight to login", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("skip-gate").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Every decision");
});

test("A2: Skip intro during the intro, and Esc, go straight to login", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("kick-off").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "intro");
  await page.getByTestId("skip-intro").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");

  await page.goto("/login");
  await page.getByTestId("kick-off").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "intro");
  await page.keyboard.press("Escape");
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");

  await page.goto("/login");
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "gate");
  await page.keyboard.press("Escape");
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
});

test("A5: reduced motion shows the login state on Kick off, with no running animations", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByTestId("kick-off").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
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
  await page.getByTestId("skip-gate").click();
  await expect(page.locator(".ath")).toHaveCount(2);
  await expect(page.locator(".pl")).toHaveCount(0);
  await expect(page.locator(".tag")).toHaveCount(2);
});

test("A6: keyboard-only order reaches every control with visible focus", async ({ page }) => {
  await page.goto("/login");
  // the gate: Kick off, then Skip intro
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("kick-off")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("skip-gate")).toBeFocused();
  await page.keyboard.press("Enter"); // Skip -> login
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
  // entering the login state parks focus on the card (so Tab reaches Continue with Google first); Shift+Tab from there
  // reaches the header's sound toggle, and the forward order is walked from that toggle
  await expect(page.getByTestId("sign-in-card")).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByTestId("sound-toggle")).toBeFocused();

  const seen: string[] = [];
  for (let i = 0; i < 12; i++) {
    if (i > 0) await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      if (el.tagName === "NEXTJS-PORTAL") return { id: "nextjs-portal (dev overlay, skipped)", ring: true, outline: "" };
      const cs = getComputedStyle(el);
      const ring = el.matches(":focus-visible") && cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2;
      return { id: el.getAttribute("data-testid") || el.id || el.textContent?.trim().slice(0, 24) || el.tagName, ring, outline: cs.outlineColor };
    });
    if (!info) break;
    seen.push(`${info.id}${info.ring ? "" : " (NO RING)"}`);
    if (!info.ring) throw new Error(`no visible focus ring on ${info.id} (outline ${info.outline})`);
  }
  console.log(`A6 tab order: ${seen.join(" -> ")}`);
  for (const must of ["sound-toggle", "google", "c-email", "send-code", "Privacy", "About"]) {
    expect(seen.some((s) => s.startsWith(must))).toBe(true);
  }
});
