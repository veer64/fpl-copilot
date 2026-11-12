import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { ChatExperience } from "@/components/chat/ChatExperience";
import { loginUrlFor } from "@/lib/redirects";
import "../../home/home.css";
import "../chat.css";
import "../../home/draft.css";

export const metadata: Metadata = { title: "Chat" };

/** /chat/{chatId}: a past chat reopened in its own team (its messages, sources, previews and feedback restored) -- Prompt
 *  W4. An unknown or another user's id silently opens a new chat in the current context. Signed-in only. */
export default function ChatThreadPage(props: PageProps<"/chat/[chatId]">) {
  return (
    <Suspense fallback={<div className="ch" aria-busy="true" />}>
      <Protected params={props.params} />
    </Suspense>
  );
}

async function Protected({ params }: { params: PageProps<"/chat/[chatId]">["params"] }) {
  const { userId } = await auth();
  const { chatId } = await params;
  if (!userId) redirect(loginUrlFor(`/chat/${encodeURIComponent(chatId)}`));
  return <ChatExperience key={chatId} chatId={chatId} />;
}
