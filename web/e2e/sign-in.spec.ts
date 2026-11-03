import { expect, test, type Page } from "@playwright/test";
import { createTestUser, deleteUser, findTestUsers, testEmail } from "./clerk-users";

/** Prompt W1 Part 5: the email-code sign-in end to end (A3) -- a +clerk_test user, the code 424242, /teams, and GET /me
 *  on the laptop backend with the browser's session token (azp) -- the wrong-code state (A4), and the sign-up fallback for
 *  a new email. Desktop project only; the backend must be running in clerk mode (see README). */

test.describe.configure({ mode: "serial" });

const created: string[] = [];
const NAMES = { existing: "w1a", fresh: "w1b" };

const desktopOnly = () => test.info().project.name === "desktop"; // one browser is enough for the Clerk flows

test.beforeAll(async () => {
  if (!desktopOnly()) return; // no Clerk user for a project whose tests all skip
  const u = await createTestUser(NAMES.existing);
  created.push(u.id);
  console.log(`Clerk test user created: ${u.id} (${NAMES.existing}+clerk_test)`);
});

test.afterAll(async () => {
  if (!desktopOnly()) return;
  // the sign-up fallback may have created a second user: find it by address before deleting everything of ours
  for (const id of await findTestUsers(NAMES.fresh)) if (!created.includes(id)) created.push(id);
  let deleted = 0;
  for (const id of created) if (await deleteUser(id)) deleted++;
  console.log(`Clerk test users deleted: ${deleted} of ${created.length}`);
  for (const n of Object.values(NAMES)) expect(await findTestUsers(n)).toHaveLength(0);
});

async function toLogin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("skip-intro").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
}

async function sendCode(page: Page, email: string) {
  await page.locator("#c-email").fill(email);
  await page.getByTestId("send-code").click();
  await expect(page.getByTestId("code-sent-title")).toHaveText("Check your email");
  await expect(page.getByTestId("code-sent-email")).toHaveText(email);
}

const SHOTS = process.env.W1_SHOTS ?? "C:\\dev\\fpl-backups\\w1_login_files";

test("A4: a wrong code shows the error, announces it, clears the slots and refocuses", async ({ page }) => {
  test.skip(test.info().project.name !== "desktop", "one browser is enough for the Clerk flows");
  await toLogin(page);
  await sendCode(page, testEmail(NAMES.existing));
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${SHOTS}\\code_sent_1440x900.png` });
  const otp = page.getByTestId("otp"); // input-otp's own <input>: the slots are presentation
  await otp.fill("111111");
  const err = page.getByTestId("code-error");
  await expect(err).toHaveText("That code isn’t right. Check your email and try again.");
  await page.screenshot({ path: `${SHOTS}\\code_wrong_1440x900.png` });
  await expect(err).toHaveAttribute("role", "alert");
  await expect(otp).toHaveValue("");
  await expect(otp).toBeFocused();
  const describedBy = (await otp.getAttribute("aria-describedby")) ?? "";
  expect(describedBy.split(/\s+/)).toContain(await err.getAttribute("id"));
  await expect(otp).toHaveAttribute("aria-invalid", "true");
});

test("A3: email code 424242 reaches /teams and GET /me answers 200 with the browser token", async ({ page }) => {
  test.skip(test.info().project.name !== "desktop", "one browser is enough for the Clerk flows");
  await toLogin(page);
  await sendCode(page, testEmail(NAMES.existing));
  await page.getByTestId("otp").fill("424242");
  await page.waitForURL("**/teams", { timeout: 20_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Signed in as w***@e***");
  await expect(page.getByTestId("me-status")).toHaveText("200", { timeout: 20_000 });
  const me = JSON.parse((await page.getByTestId("me-json").textContent()) ?? "{}") as { user_id?: number; is_admin?: boolean };
  expect(typeof me.user_id).toBe("number");
  expect(typeof me.is_admin).toBe("boolean");
  console.log(`A3 /me -> 200, user_id=${me.user_id}, is_admin=${me.is_admin}`);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL("**/login**", { timeout: 15_000 });
});

test("sign-up fallback: a new +clerk_test email gets a code; the outcome after 424242 is recorded", async ({ page }) => {
  test.skip(test.info().project.name !== "desktop", "one browser is enough for the Clerk flows");
  await toLogin(page);
  await sendCode(page, testEmail(NAMES.fresh));
  await page.getByTestId("otp").fill("424242");
  const outcome = await Promise.race([
    page.waitForURL("**/teams", { timeout: 20_000 }).then(() => "teams"),
    page.getByTestId("code-error").waitFor({ timeout: 20_000 }).then(async () => `error: ${await page.getByTestId("code-error").textContent()}`),
  ]);
  console.log(`sign-up fallback outcome: ${outcome}`);
  if (outcome === "teams") {
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL("**/login**", { timeout: 15_000 });
  }
});
