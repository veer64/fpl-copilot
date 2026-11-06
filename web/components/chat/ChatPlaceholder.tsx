"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { ErrorBox } from "@/components/home/ErrorBox";
import { AccountMenu, Logo } from "@/components/home/HomeHeader";
import { teamName } from "@/components/home/TeamCard";
import { useResource } from "@/components/home/useResource";

/** The Chat page does not exist yet (a later prompt). This placeholder shows only what Home handed over: the context
 *  (a team, or "general"), the thread the chat will use, and a prefilled question -- all read from the backend. */
export function ChatPlaceholder({ team, q, chatId }: { team?: string; q?: string; chatId?: string }) {
  const [me, reloadMe] = useResource(api.me);
  const [teams, reloadTeams] = useResource(api.teams);
  const [threads, reloadThreads] = useResource(api.threads);

  const teamId = team && /^\d+$/.test(team) ? Number(team) : null;
  const thread = threads.status === "ready" ? (chatId ? threads.data.find((t) => t.thread_id === chatId) : threads.data.find((t) => t.is_default)) : undefined;
  const card = teams.status === "ready" ? teams.data.find((t) => t.fpl_team_id === (chatId ? thread?.fpl_team_id : teamId)) : undefined;

  let context: string;
  let contextKind: "team" | "general" | "loading";
  if (chatId) {
    if (threads.status !== "ready" || teams.status !== "ready") {
      context = "…";
      contextKind = "loading";
    } else if (!thread) {
      context = "unknown thread";
      contextKind = "general";
    } else if (thread.fpl_team_id) {
      context = `${card ? teamName(card) : (thread.team_label ?? "team")} (ID ${thread.fpl_team_id})`;
      contextKind = "team";
    } else {
      context = "general";
      contextKind = "general";
    }
  } else if (teamId) {
    context = teams.status === "ready" ? `${card ? teamName(card) : "team"} (ID ${teamId})` : "…";
    contextKind = teams.status === "ready" ? "team" : "loading";
  } else if (me.status === "ready" && me.data.active_team && !chatId && q) {
    // a chip from Home keeps whatever is active: the active team, or general when none is
    context = `${me.data.active_team.label ?? "team"} (ID ${me.data.active_team.fpl_team_id}) — your active team`;
    contextKind = "team";
  } else {
    context = me.status === "ready" ? "general" : "…";
    contextKind = me.status === "ready" ? "general" : "loading";
  }

  const threadLine =
    threads.status !== "ready"
      ? "…"
      : chatId
        ? chatId
        : thread
          ? `${thread.thread_id} (your current default thread)`
          : "a new thread, created with your first message";

  const ready = me.status === "ready" && teams.status === "ready" && threads.status === "ready";
  return (
    <div className="hm" data-testid="chat-placeholder" data-context={contextKind} data-ready={ready} data-thread={chatId ?? thread?.thread_id ?? ""}>
      <div aria-hidden="true" className="hm-glow" />
      <div className="hm-col">
        <header className="hm-hdr">
          <Logo />
          <AccountMenu />
        </header>
        <main className="hm-chat">
          <div>
            <span className="hm-lbl">Chat · placeholder</span>
            <h1 style={{ margin: "8px 0 0", fontSize: 32, lineHeight: "36px", fontWeight: 600, letterSpacing: "-0.03em", color: "#F2FBFF" }}>
              The Chat page is next.
            </h1>
            <p style={{ margin: "8px 0 0", fontSize: 15, lineHeight: "22px", color: "#A9BACB" }}>
              Home handed over the context below. The conversation itself is built in a later prompt.
            </p>
          </div>
          {me.status === "error" ? (
            <ErrorBox what="your account" error={me.error} onRetry={reloadMe} />
          ) : teams.status === "error" ? (
            <ErrorBox what="your teams" error={teams.error} onRetry={reloadTeams} />
          ) : threads.status === "error" ? (
            <ErrorBox what="your chats" error={threads.error} onRetry={reloadThreads} />
          ) : (
            <section className="hm-glass" aria-label="Chat context" aria-busy={contextKind === "loading"}>
              <span className="hm-br hm-tl" aria-hidden="true" />
              <span className="hm-br hm-brr" aria-hidden="true" />
              <dl>
                <dt>Context</dt>
                <dd data-testid="chat-context">{context}</dd>
                <dt>Thread</dt>
                <dd className="mono" data-testid="chat-thread" style={{ fontSize: 13 }}>
                  {threadLine}
                </dd>
                <dt>Question</dt>
                <dd data-testid="chat-question">{q ? q : <span style={{ color: "#8A9BB0" }}>none prefilled</span>}</dd>
              </dl>
            </section>
          )}
          <div>
            <Link href="/home" className="hm-btn-o" data-testid="back-home">
              ← Back to Home
            </Link>
          </div>
        </main>
      </div>
    </div>
  );
}
