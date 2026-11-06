import { expect, test } from "@playwright/test";
import { deleteUser, findTestUsers, testEmail } from "./clerk-users";

/** Prompt W2 Part 2: a NEW +clerk_test email signs up through the same card -- code 424242 -> /home (W3) -- with no password
 *  step anywhere (the dashboard's password requirement is off). The user Clerk creates is deleted afterwards. */

const NAME = "w2new";

test.afterAll(async () => {
  if (test.info().project.name !== "desktop") return;
  const ids = await findTestUsers(NAME);
  let deleted = 0;
  for (const id of ids) if (await deleteUser(id)) deleted++;
  console.log(`Clerk test users (${NAME}): found ${ids.length}, deleted ${deleted}`);
  expect(await findTestUsers(NAME)).toHaveLength(0);
});

test("W2: a new email signs up by code and lands on /home without any password step", async ({ page }) => {
  test.skip(test.info().project.name !== "desktop", "one browser is enough");
  expect(await findTestUsers(NAME)).toHaveLength(0); // genuinely new
  let passwordFieldSeen = false;
  page.on("framenavigated", () => void 0);
  const watch = setInterval(() => {
    page
      .locator('input[type="password"], [name="password"], [autocomplete="new-password"]')
      .count()
      .then((n) => {
        if (n > 0) passwordFieldSeen = true;
      })
      .catch(() => void 0);
  }, 250);

  await page.goto("/login");
  await page.getByTestId("skip-intro").click();
  await page.locator("#c-email").fill(testEmail(NAME));
  await page.getByTestId("send-code").click();
  await expect(page.getByTestId("code-sent-title")).toHaveText("Check your email");
  await expect(page.getByTestId("sign-in-card")).toHaveAttribute("data-flow", "signup"); // the sign-up path, not sign-in
  await page.getByTestId("otp").fill("424242");
  await page.waitForURL("**/home", { timeout: 20_000 }); // Prompt W3: the post-login page is /home
  clearInterval(watch);
  expect(passwordFieldSeen).toBe(false);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Welcome, manager.", { timeout: 30_000 }); // a new user
  const ids = await findTestUsers(NAME);
  expect(ids).toHaveLength(1); // Clerk created exactly one user for the address
  console.log(`W2 sign-up: new user reached /home; password field seen: ${passwordFieldSeen}; Clerk users for ${NAME}: ${ids.length}`);
  await page.getByTestId("account-menu").click();
  await page.getByTestId("sign-out").click();
  await page.waitForURL("**/login**", { timeout: 15_000 });
});
