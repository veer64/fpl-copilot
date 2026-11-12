import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { LoginExperience } from "@/components/login/LoginExperience";
import "./login.css";

export const metadata: Metadata = { title: "Sign in" };

/** /login: intro (6.2 s) -> the sign-in state, all on the client. Prompt W3: a visitor who is already signed in goes
 *  straight to /home (no intro replay) -- the session read is request-time, so it sits behind Suspense. */
export default function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return (
    <Suspense fallback={<div aria-busy="true" style={{ minHeight: "100vh", background: "#04070C" }} />}>
      <LoginOrHome searchParams={searchParams} />
    </Suspense>
  );
}

/** Prompt W9: a visitor arriving with ?reason=guest_ended always sees the login page -- the guest's session JWT can stay
 *  valid for up to a minute after the server deleted the account, and a redirect to /home would bounce them around. */
async function LoginOrHome({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { reason } = await searchParams;
  if (reason !== "guest_ended") {
    const { userId } = await auth();
    if (userId) redirect("/home");
  }
  return <LoginExperience />;
}
