"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { toast } from "sonner";
import { ApiError, api, type Feedback, type MessageRow, type TeamCardData, type ThreadRow } from "@/lib/api";
import { nextEvent } from "@/lib/time";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";
import { ConfirmDelete } from "@/components/account/ConfirmDelete";
import { ErrorBox } from "@/components/home/ErrorBox";
import { useNow, useResource } from "@/components/home/useResource";
import { ChatHeader } from "./ChatHeader";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { MessageList } from "./Messages";
import { MobileDrawer, MobileTeam } from "./MobileTeam";
import { Sidebar, readCollapsed, threadTag, writeCollapsed } from "./Sidebar";
import { TeamCardPanel, type RefreshState } from "./TeamCardPanel";
import { key, pendingPreview, type AssistantMsg, type Context, type Msg } from "./types";

const RATE_WAIT_S = 60;
const TEAM_BG = "/images/chat-team-bg.webp";
const GENERAL_BG = "/images/chat-general-bg.webp";

function fromRows(rows: MessageRow[]): Msg[] {
  return rows.map((r) =>
    r.role === "user"
      ? { kind: "user", key: key("u"), text: r.text, at: r.at }
      : { kind: "assistant", key: key("a"), messageId: r.message_id, text: r.text, at: r.at, sources: r.sources ?? [], preview: r.squad_preview ?? null, applied: r.squad_applied ?? null, feedback: r.feedback ?? null },
  );
}

function titleOf(msgs: Msg[], row: ThreadRow | undefined): string {
  if (row?.title) return row.title;
  const first = msgs.find((m) => m.kind === "user");
  if (!first || first.kind !== "user") return "New chat";
  const t = first.text.replace(/\s+/g, " ").trim();
  return t.length <= 60 ? t : `${t.slice(0, 59).trimEnd()}…`;
}

/** /chat (General), /chat?team={id} (Team), /chat?q= (prefilled, General -- or Team with ?team=), /chat/{id} (a past chat in
 *  its own team). Everything on the page comes from the backend with the browser's Clerk token; the team is activated on
 *  SEND, never on open (checkpoint C1). */
export function ChatExperience({ team, q, chatId }: { team?: string; q?: string; chatId?: string }) {
  const router = useRouter();
  const { getToken } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const narrow = useMediaQuery(NARROW);

  const teamParam = team && /^\d+$/.test(team) ? Number(team) : null;
  const [ctx, setCtx] = useState<Context | null>(chatId ? null : teamParam ? { kind: "team", teamId: teamParam } : { kind: "general" });
  const [threadId, setThreadId] = useState<string | null>(chatId ?? null);
  const threadRef = useRef<string | null>(chatId ?? null);
  const activeTeam = useRef<number | null | undefined>(undefined); // undefined until /me answers
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState(q ?? "");
  const [prefilled, setPrefilled] = useState(!!q);
  const [busy, setBusy] = useState(false);
  const [limitUntil, setLimitUntil] = useState<string | null>(null);
  const [rateUntil, setRateUntil] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [panel, setPanel] = useState(false);
  const [cardOpen, setCardOpen] = useState(true);
  const [refresh, setRefresh] = useState<RefreshState>("idle");
  const [opening, setOpening] = useState<"loading" | "ready" | "error">(chatId ? "loading" : "ready");
  const [openError, setOpenError] = useState<ApiError | null>(null);
  const textarea = useRef<HTMLTextAreaElement | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);

  const needFast = busy || limitUntil !== null || rateUntil !== null || msgs.some((m) => m.kind === "assistant" && m.preview);
  const now = useNow(needFast ? 1000 : 60_000);

  // ---- the reads: /me (the active team, for the send), /threads, /deadlines, the card, the past chat's messages ----------
  const [me] = useResource(api.me);
  const [threads, reloadThreads] = useResource(api.threads);
  const [deadlines, reloadDeadlines] = useResource(api.deadlines);
  const teamId = ctx?.kind === "team" ? ctx.teamId : null;
  const cardLoad = useCallback((t: Parameters<typeof api.teamCard>[0]) => (teamId ? api.teamCard(t, teamId) : Promise.resolve(null)), [teamId]);
  const [card, reloadCard] = useResource<TeamCardData | null>(cardLoad);
  const messagesLoad = useCallback((t: Parameters<typeof api.messages>[0]) => (chatId ? api.messages(t, chatId) : Promise.resolve([] as MessageRow[])), [chatId]);
  const [stored, reloadStored] = useResource<MessageRow[]>(messagesLoad);

  useEffect(() => {
    if (me.status === "ready") activeTeam.current = me.data.active_team?.fpl_team_id ?? null;
  }, [me]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the remembered sidebar state, read once on the client
    setCollapsed(readCollapsed());
  }, []);

  // a past chat: its team from the /threads row (the chat's team never changes), its messages from the store
  const hydrated = useRef(false);
  useEffect(() => {
    if (!chatId || hydrated.current) return;
    if (stored.status === "error") {
      const err = stored.error;
      if (err.status === 401) {
        router.push("/login");
        return;
      }
      if (err.status === 403 || err.status === 404) {
        // silently a new chat in the current context (once /me has said which that is)
        if (me.status !== "ready") return;
        hydrated.current = true;
        const active = me.data.active_team?.fpl_team_id ?? null;
        threadRef.current = null;
        // eslint-disable-next-line react-hooks/set-state-in-effect -- the page's state comes from the fetched thread, by design (the rule reports an effect once)
        setThreadId(null);
        setCtx(active ? { kind: "team", teamId: active } : { kind: "general" });
        setOpening("ready");
        window.history.replaceState(null, "", active ? `/chat?team=${active}` : "/chat");
        return;
      }
      hydrated.current = true;
      setOpenError(err);
      setOpening("error");
      return;
    }
    if (stored.status !== "ready" || threads.status === "loading") return;
    hydrated.current = true;
    const row = threads.status === "ready" ? threads.data.find((t) => t.thread_id === chatId) : undefined;
    const rowTeam = row?.fpl_team_id ?? null;
    const fallback = me.status === "ready" ? me.data.active_team?.fpl_team_id ?? null : null;
    const tid = row ? rowTeam : fallback;
    setCtx(tid ? { kind: "team", teamId: tid } : { kind: "general" });
    setMsgs(fromRows(stored.data));
    setOpening("ready");
  }, [chatId, stored, threads, me, router]);

  const pending = useMemo(() => pendingPreview(msgs), [msgs]);
  const pendingKey = pending?.msg.key ?? null;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the brief: the phone panel opens itself when a preview arrives
    if (pendingKey && narrow) setPanel(true);
  }, [pendingKey, narrow]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, opening]);

  const cardData = card.status === "ready" ? card.data : null;
  const nextGw = deadlines.status === "ready" && now ? (nextEvent(deadlines.data.events, now)?.gw ?? null) : cardData?.next_gw ?? null;
  const row = threads.status === "ready" && threadId ? threads.data.find((t) => t.thread_id === threadId) : undefined;
  const teamName = ctx?.kind === "team" ? (row?.team_name ?? cardData?.team.name ?? null) : null;
  const tag = ctx ? (ctx.kind === "team" ? threadTag({ fpl_team_id: ctx.teamId, team_name: teamName, team_label: null }) : threadTag({ fpl_team_id: null, team_name: null, team_label: null })) : null;
  const firstName = userLoaded ? user?.firstName || user?.fullName?.split(/\s+/)[0] || null : null;
  const isNew = msgs.length === 0 && opening === "ready";

  // ---- the chat box state --------------------------------------------------------------------------------------------------
  const limited = limitUntil !== null && (!now || new Date(limitUntil).getTime() > now.getTime());
  const rated = rateUntil !== null && (!now || rateUntil > now.getTime());
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a countdown that ran out clears its own state
    if (limitUntil !== null && !limited) setLimitUntil(null);
    if (rateUntil !== null && !rated) setRateUntil(null);
  }, [limited, rated, limitUntil, rateUntil]);
  const disabledText = busy ? "Wait for the answer…" : limited ? "Daily limit reached — back at 00:00 UTC" : rated ? "Wait a minute…" : null;

  const replaceThinking = useCallback((thinkKey: string, next: Msg | null) => {
    setMsgs((m) => (next ? m.map((x) => (x.key === thinkKey ? next : x)) : m.filter((x) => x.key !== thinkKey)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || busy || !ctx || disabledText) return;
      setDraft("");
      setPrefilled(false);
      setPanel(false);
      const thinkKey = key("t");
      setMsgs((m) => [...m, { kind: "user", key: key("u"), text: question, at: new Date().toISOString() }, { kind: "thinking", key: thinkKey, startedAt: Date.now() }]);
      setBusy(true);
      try {
        // C1: the chat's team becomes the active one on SEND, only when it is not already
        if (activeTeam.current === undefined && me.status === "ready") activeTeam.current = me.data.active_team?.fpl_team_id ?? null;
        if (ctx.kind === "team" && activeTeam.current !== ctx.teamId) {
          await api.activate(getToken, ctx.teamId);
          activeTeam.current = ctx.teamId;
        } else if (ctx.kind === "general" && activeTeam.current !== null) {
          await api.deactivate(getToken);
          activeTeam.current = null;
        }
        let tid = threadRef.current;
        if (!tid) {
          tid = (await api.newThread(getToken)).thread_id;
          threadRef.current = tid;
          setThreadId(tid);
          window.history.replaceState(null, "", `/chat/${tid}`);
        }
        const reply = await api.chat(getToken, question, tid);
        if (reply.capped && reply.limit) {
          replaceThinking(thinkKey, { kind: "system", key: key("s"), variant: "limit", resetAt: reply.limit.reset_at });
          setLimitUntil(reply.limit.reset_at);
          return;
        }
        replaceThinking(thinkKey, {
          kind: "assistant",
          key: key("a"),
          messageId: reply.message_id ?? null,
          text: reply.answer,
          at: new Date().toISOString(),
          sources: reply.sources ?? [],
          preview: reply.squad_preview ?? null,
          applied: reply.squad_applied ?? null,
          feedback: null,
        });
        reloadThreads();
        if (reply.squad_applied) reloadCard();
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, e instanceof Error ? e.message : String(e));
        if (err.status === 401) {
          router.push("/login");
          return;
        }
        if (err.status === 429) {
          const until = Date.now() + (err.retryAfter ?? RATE_WAIT_S) * 1000;
          replaceThinking(thinkKey, { kind: "system", key: key("s"), variant: "rate", untilMs: until });
          setRateUntil(until);
        } else if (err.status === 409) {
          replaceThinking(thinkKey, { kind: "system", key: key("s"), variant: "team", threadId: err.threadId ?? null });
        } else {
          replaceThinking(thinkKey, { kind: "system", key: key("s"), variant: "error", question, why: err.status === 408 ? "timeout" : err.status === 0 ? "network" : `http-${err.status}` });
        }
      } finally {
        setBusy(false);
      }
    },
    [busy, ctx, disabledText, getToken, me, reloadCard, reloadThreads, replaceThinking, router],
  );

  /** d's Retry: re-read the thread first -- an answer that landed meanwhile is shown; else the question is sent once more. */
  const retry = useCallback(
    async (question: string) => {
      const tid = threadRef.current;
      setMsgs((m) => m.filter((x) => !(x.kind === "system" && x.variant === "error" && x.question === question)));
      if (tid) {
        try {
          const rows = await api.messages(getToken, tid);
          const last = rows[rows.length - 1];
          const prev = rows[rows.length - 2];
          if (last?.role === "assistant" && prev?.role === "user" && prev.text.trim() === question) {
            setMsgs(fromRows(rows));
            reloadThreads();
            return;
          }
          // the question was never answered: drop our optimistic copy of it before sending it again
          setMsgs(fromRows(rows));
        } catch {
          setMsgs((m) => m.filter((x) => !(x.kind === "user" && x.text === question)));
        }
      } else {
        setMsgs((m) => m.filter((x) => !(x.kind === "user" && x.text === question)));
      }
      await send(question);
    },
    [getToken, reloadThreads, send],
  );

  const newChat = useCallback(() => {
    setDrawer(false);
    router.push(ctx?.kind === "team" ? `/chat?team=${ctx.teamId}` : "/chat");
  }, [ctx, router]);
  // Prompt W5: Delete chat -- the trash on a row opens the shared confirm; DELETE /threads/{id}; the row goes; the open
  // chat deleted -> a new empty chat in the same team / General
  const [deleting, setDeleting] = useState<ThreadRow | null>(null);
  const deleteOpener = useRef<HTMLElement | null>(null);
  const askDelete = (t: ThreadRow) => {
    deleteOpener.current = document.activeElement as HTMLElement | null;
    setDeleting(t);
  };
  const confirmDelete = async () => {
    if (!deleting) return;
    const t = deleting;
    try {
      await api.deleteThread(getToken, t.thread_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.push("/login");
      throw e;
    }
    setDeleting(null);
    reloadThreads();
    if (t.thread_id === threadRef.current) newChat();
  };
  const openThread = useCallback(
    (t: ThreadRow) => {
      setDrawer(false);
      router.push(`/chat/${t.thread_id}`);
    },
    [router],
  );
  const feedback = useCallback(
    async (m: AssistantMsg, score: Feedback) => {
      if (!m.messageId) return;
      const before = m.feedback;
      setMsgs((all) => all.map((x) => (x.key === m.key && x.kind === "assistant" ? { ...x, feedback: score } : x)));
      try {
        await api.feedback(getToken, m.messageId, score);
      } catch (e) {
        setMsgs((all) => all.map((x) => (x.key === m.key && x.kind === "assistant" ? { ...x, feedback: before } : x)));
        if (e instanceof ApiError && e.status === 401) router.push("/login");
        else toast.error("Couldn’t save your feedback");
      }
    },
    [getToken, router],
  );
  const doRefresh = useCallback(async () => {
    if (!teamId) return;
    setRefresh("busy");
    try {
      await api.refresh(getToken, teamId);
      setRefresh("idle");
      reloadCard();
    } catch (e) {
      setRefresh(e instanceof ApiError && e.status === 429 ? "limited" : "failed");
      if (e instanceof ApiError && e.status === 401) router.push("/login");
    }
  }, [teamId, getToken, reloadCard, router]);
  const chip = (text: string) => {
    setDraft(text);
    setPrefilled(false);
    textarea.current?.focus();
  };
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      writeCollapsed(!c);
      return !c;
    });
  };
  const onDeadlinesExpired = useCallback(() => reloadDeadlines(), [reloadDeadlines]);

  const general = ctx?.kind === "general";
  const newRow = isNew && tag ? tag : null;
  const placeholder = ctx?.kind === "team" ? `Ask about ${teamName ?? "your team"}…` : "Ask anything about FPL…";

  return (
    <div className="ch" data-testid="chat" data-context={ctx?.kind ?? "loading"} data-team-id={teamId ?? ""} data-thread-id={threadId ?? ""} data-ready={opening === "ready"} data-busy={busy}>
      <ChatHeader deadlines={deadlines} now={now} onExpired={onDeadlinesExpired} onMenu={() => setDrawer(true)} isOwner={me.status === "ready" ? me.data.is_owner : null} isAdmin={me.status === "ready" ? me.data.is_admin : null} />
      <div className="ch-body">
        {!general && (
          <div aria-hidden="true" className={`ch-bg${collapsed ? " collapsed" : ""}`}>
            {/* eslint-disable-next-line @next/next/no-img-element -- the design's background photo, masked; decorative */}
            <img src={TEAM_BG} alt="" />
          </div>
        )}
        <Sidebar collapsed={collapsed} onToggle={toggleCollapsed} onNew={newChat} threads={threads} currentId={threadId} newRow={newRow} now={now} onOpen={openThread} onDelete={askDelete} />
        <main className={`ch-main${general ? " general" : ""}`}>
          {general && (
            <>
              <div aria-hidden="true" className="ch-gen-glow" />
              {/* eslint-disable-next-line @next/next/no-img-element -- the design's background photo, masked; decorative */}
              <img src={GENERAL_BG} alt="" aria-hidden="true" className="ch-gen-photo" />
              <div aria-hidden="true" className="ch-gen-grid" />
            </>
          )}
          <div className="ch-title">
            <h1 data-testid="chat-title">{titleOf(msgs, row)}</h1>
            {tag && (
              <span className={tag.cls} data-testid="chat-tag">
                {tag.text}
              </span>
            )}
          </div>
          {narrow && ctx?.kind === "team" && (
            <MobileTeam card={card as Parameters<typeof MobileTeam>[0]["card"]} preview={pending?.preview ?? null} open={panel} onToggle={() => setPanel((p) => !p)} refresh={refresh} onRefresh={doRefresh} onRetry={reloadCard} teamName={teamName} />
          )}
          <div className="ch-scroll" ref={scroller}>
            <div className="ch-thread" data-testid="thread">
              {opening === "loading" && (
                <div className="ch-sk-chat" aria-label="Loading chat" aria-busy="true" data-testid="chat-skeleton">
                  <span className="ch-sk" style={{ height: 36, width: "56%", alignSelf: "flex-end", borderRadius: "14px 14px 4px 14px" }} />
                  <div className="ch-sk-ai">
                    <span className="ch-sk" style={{ width: 26, height: 26, flexShrink: 0 }} />
                    <div>
                      <span className="ch-sk" style={{ height: 11 }} />
                      <span className="ch-sk" style={{ height: 11, width: "92%" }} />
                      <span className="ch-sk" style={{ height: 11, width: "64%" }} />
                    </div>
                  </div>
                </div>
              )}
              {opening === "error" && openError && (
                <ErrorBox
                  what="this chat"
                  error={openError}
                  onRetry={() => {
                    hydrated.current = false;
                    setOpening("loading");
                    reloadStored();
                  }}
                />
              )}
              {isNew && ctx && <EmptyState mode={ctx.kind} teamName={teamName} nextGw={nextGw} card={cardData} firstName={firstName} onChip={chip} />}
              {msgs.length > 0 && (
                <MessageList msgs={msgs} now={now} phone={narrow} onYes={() => send("Yes")} onNo={() => send("No")} onRetry={retry} onStartNew={newChat} onFeedback={feedback} />
              )}
            </div>
          </div>
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => send(draft)}
            disabledText={disabledText}
            placeholder={placeholder}
            prefilled={prefilled}
            prefilledNote={narrow ? "Ready to send" : "Ready to send — edit it if you like."}
            textareaRef={textarea}
            onTyping={() => {
              setPrefilled(false);
              setPanel(false);
            }}
            ariaLabel={placeholder.replace(/…$/, "")}
          />
        </main>
        {!narrow && ctx?.kind === "team" && (
          <div className="ch-right">
            <TeamCardPanel card={card as Parameters<typeof TeamCardPanel>[0]["card"]} preview={pending?.preview ?? null} refresh={refresh} onRefresh={doRefresh} onRetry={reloadCard} open={cardOpen} onToggle={() => setCardOpen((o) => !o)} teamName={teamName} />
          </div>
        )}
      </div>
      {narrow && drawer && <MobileDrawer onClose={() => setDrawer(false)} onNew={newChat} threads={threads} currentId={threadId} newRow={newRow} now={now} onOpen={openThread} onDelete={askDelete} />}
      <ConfirmDelete
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Delete this chat?"
        intro={
          <>
            <strong>“{deleting?.title ?? "New chat"}”</strong> and its messages will be removed.
          </>
        }
        warning="This can’t be undone."
        confirmLabel="Delete chat"
        busyLabel="Deleting…"
        errorFor={() => "Couldn’t delete this chat — try again."}
        onConfirm={confirmDelete}
        returnTo={deleteOpener}
        testId="delete-chat"
      />
    </div>
  );
}
