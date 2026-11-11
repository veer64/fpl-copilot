import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { ChatExperience } from "@/components/chat/ChatExperience";
import { loginUrlFor } from "@/lib/redirects";
import "../home/home.css";
import "./chat.css";

export const metadata: Metadata = { title: "Chat" };

/** /chat (General), /chat?team={id} (Team), /chat?q={question} (prefilled, not sent; General unless ?team= is given too) --
 *  Prompt W4. Signed-in only. */
export default function ChatPage(props: PageProps<"/chat">) {
  return (
    <Suspense fallback={<div className="ch" aria-busy="true" />}>
      <Protected searchParams={props.searchParams} />
    </Suspense>
  );
}

async function Protected({ searchParams }: { searchParams: PageProps<"/chat">["searchParams"] }) {
  const { userId } = await auth();
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const team = one(sp.team);
  const q = one(sp.q);
  if (!userId) {
    const qs = new URLSearchParams();
    if (team) qs.set("team", team);
    if (q) qs.set("q", q);
    redirect(loginUrlFor(`/chat${qs.size ? `?${qs}` : ""}`));
  }
  // a new context is a new page (its reads start again), even when only the search params changed
  return <ChatExperience key={`${team ?? ""}|${q ?? ""}`} team={team} q={q} />;
}
