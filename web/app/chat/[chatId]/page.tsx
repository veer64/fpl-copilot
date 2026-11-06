import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { ChatPlaceholder } from "@/components/chat/ChatPlaceholder";
import "../../home/home.css";

export const metadata: Metadata = { title: "Chat" };

/** /chat/{chatId}: a recent chat reopened -- the placeholder names the thread and its team (Prompt W3). Signed-in only. */
export default function ChatThreadPage(props: PageProps<"/chat/[chatId]">) {
  return (
    <Suspense fallback={<div className="hm" aria-busy="true" />}>
      <Protected params={props.params} />
    </Suspense>
  );
}

async function Protected({ params }: { params: PageProps<"/chat/[chatId]">["params"] }) {
  const { userId } = await auth();
  if (!userId) redirect("/login");
  const { chatId } = await params;
  return <ChatPlaceholder chatId={chatId} />;
}
