import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { ChatPlaceholder } from "@/components/chat/ChatPlaceholder";
import "../home/home.css";

export const metadata: Metadata = { title: "Chat" };

/** /chat?team={id} | /chat?q={question} | /chat -- the placeholder until the Chat page is built (Prompt W3). Signed-in only. */
export default function ChatPage(props: PageProps<"/chat">) {
  return (
    <Suspense fallback={<div className="hm" aria-busy="true" />}>
      <Protected searchParams={props.searchParams} />
    </Suspense>
  );
}

async function Protected({ searchParams }: { searchParams: PageProps<"/chat">["searchParams"] }) {
  const { userId } = await auth();
  if (!userId) redirect("/login");
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const team = one(sp.team);
  const q = one(sp.q);
  // a new context is a new placeholder (its reads start again), even when only the search params changed
  return <ChatPlaceholder key={`${team ?? ""}|${q ?? ""}`} team={team} q={q} />;
}
