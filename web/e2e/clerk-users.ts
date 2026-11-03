import fs from "node:fs";
import path from "node:path";

/** Clerk test users for the browser checks (Prompt W1): only `<name>+clerk_test@example.com` addresses, which Clerk's
 *  test mode accepts with the code 424242 and never emails. Created and deleted through the Backend API with the secret
 *  key from web/.env.local (read here, never printed). */

const BACKEND = "https://api.clerk.com/v1";

export function secretKey(): string {
  const env = fs.readFileSync(path.join(process.cwd(), ".env.local"), "utf8");
  const line = env.split(/\r?\n/).find((l) => l.startsWith("CLERK_SECRET_KEY="));
  if (!line) throw new Error("CLERK_SECRET_KEY missing from web/.env.local");
  return line.slice("CLERK_SECRET_KEY=".length).trim().replace(/^"|"$/g, "");
}

async function api(method: string, route: string, body?: unknown) {
  const res = await fetch(`${BACKEND}${route}`, {
    method,
    headers: { Authorization: `Bearer ${secretKey()}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  return { status: res.status, json };
}

export function testEmail(name: string): string {
  if (!/^[a-z0-9]+$/.test(name)) throw new Error("test user names are lower-case letters and digits only");
  return `${name}+clerk_test@example.com`;
}

export async function createTestUser(name: string): Promise<{ id: string; email: string }> {
  const email = testEmail(name);
  const r = await api("POST", "/users", { email_address: [email], skip_password_requirement: true });
  if (r.status !== 200) throw new Error(`Clerk create user: HTTP ${r.status} ${JSON.stringify(r.json).slice(0, 200)}`);
  return { id: (r.json as { id: string }).id, email };
}

export async function findTestUsers(name: string): Promise<string[]> {
  const r = await api("GET", `/users?email_address=${encodeURIComponent(testEmail(name))}`);
  if (r.status !== 200) return [];
  return (r.json as { id: string }[]).map((u) => u.id);
}

export async function deleteUser(id: string): Promise<boolean> {
  const r = await api("DELETE", `/users/${id}`);
  return r.status === 200 || r.status === 404;
}
