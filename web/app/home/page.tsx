import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { HomeExperience } from "@/components/home/HomeExperience";
import { loginUrlFor } from "@/lib/redirects";
import "./home.css";

export const metadata: Metadata = { title: "Home" };

/** /home (Prompt W3): signed-in users only -- a signed-out visitor is sent to /login before anything renders. The session
 *  read is request-time, so with Cache Components it sits behind Suspense and streams in; the shell outside is static. */
export default function HomePage() {
  return (
    <Suspense fallback={<div className="hm" aria-busy="true" />}>
      <Protected />
    </Suspense>
  );
}

async function Protected() {
  const { userId } = await auth();
  if (!userId) redirect(loginUrlFor("/home"));
  return <HomeExperience />;
}
