import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { TeamsPlaceholder } from "@/components/teams/TeamsPlaceholder";

export const metadata: Metadata = { title: "Teams" };

/** Protected: a signed-out visitor is sent to /login before anything renders (Prompt W1 Part 1). The session read is
 *  request-time, so with Cache Components it sits behind Suspense and streams in; the shell outside is static. */
export default function TeamsPage() {
  return (
    <Suspense fallback={<main className="p-6 text-fpl-muted">Loading…</main>}>
      <Protected />
    </Suspense>
  );
}

async function Protected() {
  const { userId } = await auth();
  if (!userId) redirect("/login");
  return <TeamsPlaceholder />;
}
