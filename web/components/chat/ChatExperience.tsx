"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { toast } from "sonner";
import { ApiError, api, type DraftResult, type Feedback, type MessageRow, type TeamCardData, type ThreadRow } from "@/lib/api";
import { OPENING_CHIPS, answerChips, unusedChips, type DraftChip } from "@/lib/draft-chips";
import { AddTeamDialog, ADD_COPY } from "@/components/home/AddTeamDialog";
import { BuildFailedDialog, BuildingDialog, RebuildConfirm, useDraftBuild } from "@/components/draft/BuildFlow";
import { EnterGuide } from "@/components/draft/EnterGuide";
import { DraftPanel, MobileDraft } from "./DraftPanel";
import { nextEvent } from "@/lib/time";
import { NARROW, REDUCED_MOTION, useMediaQuery } from "@/lib/useMediaQuery";
import { ConfirmDelete } from "@/components/account/ConfirmDelete";
import { ErrorBox } from "@/components/home/ErrorBox";
import { useNow, useResource } from "@/components/home/useResource";
import { GuestSession } from "@/components/guest/GuestSession";
import { ChatHeader } from "./ChatHeader";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { MessageList } from "./Messages";
import { MobileDrawer, MobileTeam } from "./MobileTeam";
import { Sidebar, readCollapsed, threadTag, writeCollapsed } from "./Sidebar";
import { TeamCardPanel, type RefreshState } from "./TeamCardPanel";
import { finishReveal, key, pendingPreview, type AssistantMsg, type Context, type Msg } from "./types";
import { loginSignedOut, useSignedOutRedirect } from "@/lib/session";

const RESUME_POLL_MS = 5000;        // W7b (F3): a reload during an answer re-reads the thread every ~5 s ...
const RESUME_MAX_MS = 120_000;      // ... for at most 2 minutes, then the error state with Retry
const DRAFT_PREFIX = "fpl.draft.";  // W7b (F2): the unsent question, per chat, in sessionStorage

function readDraft(k: string): string {
  try {
    return window.sessionStorage.getItem(DRAFT_PREFIX + k) ?? "";
  } catch {
    return "";
  }
}
function writeDraft(k: string, v: string) {
  try {
    if (v) window.sessionStorage.setItem(DRAFT_PREFIX + k, v);
    else window.sessionStorage.removeItem(DRAFT_PREFIX + k);
  } catch {
    /* no storage */
  }
}

const RATE_WAIT_S = 60;
// W10 (2026-11-12), replacing W8a's "follow the new answer at the bottom": on send (and when a saved chat opens) the latest
// question goes to the top of the box, TURN_GAP_PX below its edge; the answer then grows downward and the view never moves.
// The round down-arrow shows whenever the reader is more than AT_BOTTOM_PX from the bottom.
const TURN_GAP_PX = 16;
const AT_BOTTOM_PX = 24;
const TEAM_BG = "/images/chat-team-bg.webp";
const GENERAL_BG = "/images/chat-general-bg.webp";

function fromRows(rows: MessageRow[]): Msg[] {
  const out: Msg[] = [];
  for (const r of rows) {
    if (r.role === "user") out.push({ kind: "user", key: key("u"), text: r.text, at: r.at });
    else if (r.role === "pending") {
      // W7b: the question whose answer is being written: shown with the thinking row, from the server's started_at
      out.push({ kind: "user", key: key("u"), text: r.text, at: r.started_at });
      out.push({ kind: "thinking", key: key("t"), startedAt: r.started_at ? Date.parse(r.started_at) : Date.now(), resumed: true, question: r.text });
    } else
      out.push({
        kind: "assistant",
        key: key("a"),
        messageId: r.message_id,
        text: r.text,
        at: r.at,
        sources: r.sources ?? [],
        preview: r.squad_preview ?? null,
        applied: r.squad_applied ?? null,
        feedback: r.feedback ?? null,
        ...(r.kind === "draft_opening" ? { opening: true } : {}), // W11: the draft chat's fixed opening message
      });
  }
  return out;
}

function titleOf(msgs: Msg[], row: ThreadRow | undefined, draft = false): string {
  if (row?.title) return row.title;
  const first = msgs.find((m) => m.kind === "user");
  if (!first || first.kind !== "user") return draft ? "Your draft team" : "New chat"; // W11: a draft chat before its first question
  const t = first.text.replace(/\s+/g, " ").trim();
  return t.length <= 60 ? t : `${t.slice(0, 59).trimEnd()}…`;
}

/** /chat (General), /chat?team={id} (Team), /chat?q= (prefilled, General -- or Team with ?team=), /chat/{id} (a past chat in
 *  its own team). Everything on the page comes from the backend with the browser's Clerk token; the team is activated on
 *  SEND, never on open (checkpoint C1). */
export function ChatExperience({ team, q, chatId, draft: draftParam }: { team?: string; q?: string; chatId?: string; draft?: boolean }) {
  const router = useRouter();
  const { getToken } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const narrow = useMediaQuery(NARROW);

  const teamParam = team && /^\d+$/.test(team) ? Number(team) : null;
  const [ctx, setCtx] = useState<Context | null>(chatId ? null : draftParam ? { kind: "draft" } : teamParam ? { kind: "team", teamId: teamParam } : { kind: "general" });
  const [threadId, setThreadId] = useState<string | null>(chatId ?? null);
  const threadRef = useRef<string | null>(chatId ?? null);
  const activeTeam = useRef<number | null | undefined>(undefined); // undefined until /me answers
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraftState] = useState(q ?? "");
  useSignedOutRedirect();
  const [prefilled, setPrefilled] = useState(!!q);
  const [busy, setBusy] = useState(false);
  const [limitUntil, setLimitUntil] = useState<string | null>(null);
  const [guestBlocked, setGuestBlocked] = useState<string | null>(null); // W9: a guest refusal disables the box with its own text
  const [rateUntil, setRateUntil] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [panel, setPanel] = useState(false);
  const [cardOpen, setCardOpen] = useState(true);
  const [refresh, setRefresh] = useState<RefreshState>("idle");
  const [opening, setOpening] = useState<"loading" | "ready" | "error">(chatId ? "loading" : "ready");
  // W7b (F2): the unsent question is kept per chat (sessionStorage) -- saved as you type, restored when you come back, cleared on send
  const draftKey = threadId ?? (draftParam ? "new-draft" : teamParam ? `new-team-${teamParam}` : "new-general");
  const setDraft = useCallback(
    (v: string) => {
      setDraftState(v);
      writeDraft(draftKey, v);
    },
    [draftKey],
  );
  useEffect(() => {
    if (q) return; // a prefilled question wins
    const saved = readDraft(draftKey);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the remembered draft of this chat, read once per chat
    if (saved) setDraftState(saved);
  }, [draftKey, q]);
  const [openError, setOpenError] = useState<ApiError | null>(null);
  const textarea = useRef<HTMLTextAreaElement | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const scrollIntent = useRef<"last-turn" | null>(null); // W10: set by a send or a chat opening, consumed by the layout effect

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
  // Prompt W11: the draft -- read for a draft chat, and for any reopened chat (a draft chat with only its opening message is
  // not in /threads yet, W4's rule: its id is in the draft's thread_ids)
  const wantDraft = !!chatId || ctx?.kind === "draft";
  const draftLoad = useCallback((t: Parameters<typeof api.draft>[0]) => (wantDraft ? api.draft(t) : Promise.resolve({ draft: null } as DraftResult)), [wantDraft]);
  const [draftRes, reloadDraft] = useResource<DraftResult>(draftLoad);
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
        loginSignedOut(router);
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
    const row = threads.status === "ready" ? threads.data.find((t) => t.thread_id === chatId) : undefined;
    if (!row?.is_draft && draftRes.status === "loading") return; // W11: an unlisted chat may be the draft's
    hydrated.current = true;
    const isDraft = !!row?.is_draft || (draftRes.status === "ready" && !!draftRes.data.draft?.thread_ids.includes(chatId));
    const rowTeam = row?.fpl_team_id ?? null;
    const fallback = me.status === "ready" ? me.data.active_team?.fpl_team_id ?? null : null;
    const tid = row ? rowTeam : fallback;
    setCtx(isDraft ? { kind: "draft" } : tid ? { kind: "team", teamId: tid } : { kind: "general" });
    scrollIntent.current = "last-turn"; // W10: a reopened chat lands with its last question at the top
    setMsgs(fromRows(stored.data));
    setOpening("ready");
  }, [chatId, stored, threads, me, router, draftRes]);

  const pending = useMemo(() => pendingPreview(msgs), [msgs]);
  const pendingKey = pending?.msg.key ?? null;

  // W7b (F3): an answer that was in flight when the page loaded -- re-read the thread every RESUME_POLL_MS until the pending
  // row is gone (the answer appears, no re-send), or give up after RESUME_MAX_MS with the error state and its Retry
  const resumed = useMemo(() => msgs.find((m): m is Extract<Msg, { kind: "thinking" }> => m.kind === "thinking" && !!m.resumed) ?? null, [msgs]);
  const resumedKey = resumed?.key ?? null;
  const resumedStart = resumed?.startedAt ?? 0;
  const resumedQuestion = resumed?.question ?? "";
  useEffect(() => {
    if (!resumedKey || !chatId) return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      if (Date.now() - resumedStart > RESUME_MAX_MS) {
        setMsgs((m) => m.map((x) => (x.key === resumedKey ? { kind: "system", key: key("s"), variant: "error", question: resumedQuestion, why: "timeout" } : x)));
        return;
      }
      try {
        const rows = await api.messages(getToken, chatId);
        if (stop) return;
        if (!rows.some((r) => r.role === "pending")) {
          setMsgs(fromRows(rows));
          reloadThreads();
          return;
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) loginSignedOut(router);
      }
      timer = window.setTimeout(tick, RESUME_POLL_MS);
    };
    let timer = window.setTimeout(tick, RESUME_POLL_MS);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [resumedKey, resumedStart, resumedQuestion, chatId, getToken, reloadThreads, router]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the brief: the phone panel opens itself when a preview arrives
    if (pendingKey && narrow) setPanel(true);
  }, [pendingKey, narrow]);
  // W10: the scroll rule. The box only ever moves for (1) a send and (2) a saved chat opening: the latest question goes to the
  // top of the box (the last turn's min-height, --ch-turn-min, guarantees the room). An answer arriving or writing itself
  // out, a reader who scrolled away, the music, the page's ticks and a card reload never move it (overflow-anchor is off on
  // the box, so nothing else does either). The down-arrow tracks the distance to the bottom on scroll and as content grows.
  const [showDown, setShowDown] = useState(false);
  const reducedMotion = useMediaQuery(REDUCED_MOTION);
  const measureDown = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    const away = el.scrollHeight - el.scrollTop - el.clientHeight > AT_BOTTOM_PX;
    setShowDown((v) => (v === away ? v : away));
  }, []);
  const downFrame = useRef(0);
  const onThreadScroll = useCallback(() => {
    if (downFrame.current) return;
    downFrame.current = window.requestAnimationFrame(() => {
      downFrame.current = 0;
      measureDown();
    });
  }, [measureDown]);
  const setTurnMin = useCallback((el: HTMLElement) => el.style.setProperty("--ch-turn-min", `${Math.max(0, el.clientHeight - TURN_GAP_PX)}px`), []);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const setMin = () => setTurnMin(el);
    setMin();
    const thread = el.querySelector(".ch-thread");
    const ro = new ResizeObserver(() => {
      setMin();
      measureDown();
    });
    ro.observe(el);
    if (thread) ro.observe(thread);
    return () => {
      ro.disconnect();
      if (downFrame.current) window.cancelAnimationFrame(downFrame.current);
    };
  }, [measureDown, setTurnMin]);
  useLayoutEffect(() => {
    if (scrollIntent.current !== "last-turn") return;
    const el = scroller.current;
    const turn = el?.querySelector<HTMLElement>('.ch-turn[data-last="true"]');
    if (!el || !turn) return;
    scrollIntent.current = null;
    setTurnMin(el); // the box may have just changed height (the composer shrinks when the sent text is cleared)
    el.scrollTop = Math.max(0, turn.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - TURN_GAP_PX);
    measureDown();
  }, [msgs, measureDown, setTurnMin]);
  const toBottom = useCallback(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
  }, [reducedMotion]);
  // W10: a hidden tab finishes every answer that is still writing itself out (no timer keeps running behind it)
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) setMsgs(finishReveal);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const cardData = card.status === "ready" ? card.data : null;
  const nextGw = deadlines.status === "ready" && now ? (nextEvent(deadlines.data.events, now)?.gw ?? null) : cardData?.next_gw ?? null;
  const row = threads.status === "ready" && threadId ? threads.data.find((t) => t.thread_id === threadId) : undefined;
  const teamName = ctx?.kind === "team" ? (row?.team_name ?? cardData?.team.name ?? null) : null;
  const tag = ctx
    ? ctx.kind === "draft"
      ? threadTag({ fpl_team_id: null, team_name: null, team_label: null, is_draft: true })
      : ctx.kind === "team"
        ? threadTag({ fpl_team_id: ctx.teamId, team_name: teamName, team_label: null })
        : threadTag({ fpl_team_id: null, team_name: null, team_label: null })
    : null;
  const isDraftChat = ctx?.kind === "draft";
  const draftData = draftRes.status === "ready" ? draftRes.data.draft : null;
  const draftGone = isDraftChat && draftRes.status === "ready" && !draftData;
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
  const disabledText = busy
    ? "Wait for the answer…"
    : guestBlocked
      ? guestBlocked
      : limited
        ? "Daily limit reached — back at 00:00 UTC"
        : rated
          ? "Wait a minute…"
          : draftGone
            ? "Your draft was deleted — build a new one from Home"
            : null;

  const replaceThinking = useCallback((thinkKey: string, next: Msg | null) => {
    setMsgs((m) => (next ? m.map((x) => (x.key === thinkKey ? next : x)) : m.filter((x) => x.key !== thinkKey)));
  }, []);

  const send = useCallback(
    async (text: string, opts?: { explain?: boolean; preview?: { messageId: string; answer: "yes" | "no" } }) => {
      const question = text.trim();
      if (!question || busy || !ctx || disabledText) return;
      setDraft("");
      writeDraft(draftKey, "");
      setPrefilled(false);
      setPanel(false);
      const thinkKey = key("t");
      scrollIntent.current = "last-turn"; // W10: the question goes to the top of the box, the thinking row under it
      setMsgs((m) => [...finishReveal(m), { kind: "user", key: key("u"), text: question, at: new Date().toISOString() }, { kind: "thinking", key: thinkKey, startedAt: Date.now() }]);
      setBusy(true);
      try {
        // C1: the chat's team becomes the active one on SEND, only when it is not already
        if (activeTeam.current === undefined && me.status === "ready") activeTeam.current = me.data.active_team?.fpl_team_id ?? null;
        // W11: a draft chat never activates or deactivates a team (the server binds the turn to the draft by its thread)
        if (ctx.kind === "team" && activeTeam.current !== ctx.teamId) {
          await api.activate(getToken, ctx.teamId);
          activeTeam.current = ctx.teamId;
        } else if (ctx.kind === "general" && activeTeam.current !== null) {
          await api.deactivate(getToken);
          activeTeam.current = null;
        }
        let tid = threadRef.current;
        if (!tid) {
          tid = (ctx.kind === "draft" ? await api.newDraftThread(getToken) : await api.newThread(getToken)).thread_id;
          threadRef.current = tid;
          setThreadId(tid);
          window.history.replaceState(null, "", `/chat/${tid}`);
        }
        // W11e E2: the "Why these players?" chip is answered from code (no model call); X1: so are the preview's Yes / No
        // buttons (that preview only); everything else goes to the agent
        const reply = opts?.preview
          ? await api.previewAnswer(getToken, tid, opts.preview.messageId, opts.preview.answer)
          : opts?.explain && ctx.kind === "draft"
            ? await api.draftExplain(getToken, tid, question)
            : await api.chat(getToken, question, tid);
        if (reply.capped && reply.limit) {
          if (reply.limit.kind === "daily" && reply.limit.reset_at) {
            replaceThinking(thinkKey, { kind: "system", key: key("s"), variant: "limit", resetAt: reply.limit.reset_at });
            setLimitUntil(reply.limit.reset_at);
          } else {
            // W9: a guest refusal (the cap, the shared budget, the switch) -- the server's wording, the box disabled with it
            replaceThinking(thinkKey, { kind: "system", key: key("s"), variant: "guest", code: reply.limit.kind === "daily" ? "guest" : reply.limit.kind, text: reply.answer });
            setGuestBlocked(reply.answer);
          }
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
          reveal: true, // W10: this reply writes itself out (once, in this tab)
        });
        reloadThreads();
        if (reply.squad_applied) {
          if (ctx.kind === "draft") reloadDraft();
          else reloadCard();
        }
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, e instanceof Error ? e.message : String(e));
        if (err.status === 401) {
          writeDraft(draftKey, question); // the question is kept for after the sign-in
          loginSignedOut(router);
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
    [busy, ctx, disabledText, draftKey, getToken, me, reloadCard, reloadDraft, reloadThreads, replaceThinking, router, setDraft],
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
    router.push(ctx?.kind === "team" ? `/chat?team=${ctx.teamId}` : ctx?.kind === "draft" ? "/chat?draft=1" : "/chat");
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
      if (e instanceof ApiError && e.status === 401) loginSignedOut(router);
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
        if (e instanceof ApiError && e.status === 401) loginSignedOut(router);
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
      if (e instanceof ApiError && e.status === 401) loginSignedOut(router);
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
  // W8a: the message list is memoised -- stable callbacks, and the clock reaches it only while a message shows a countdown
  // (a preview's expiry, a limit / rate notice), so the 1 s / 60 s ticks, the music and the card reloads never re-render it
  // X1: the buttons answer THEIR preview by its message id (a typed yes / no is decided by the same server code)
  const onYes = useCallback((messageId: string | null) => send("Yes", messageId ? { preview: { messageId, answer: "yes" } } : undefined), [send]);
  const onNo = useCallback((messageId: string | null) => send("No", messageId ? { preview: { messageId, answer: "no" } } : undefined), [send]);
  const listNeedsClock = useMemo(() => msgs.some((m) => m.kind === "system" || (m.kind === "assistant" && !!m.preview)), [msgs]);
  const listNow = listNeedsClock ? now : null;

  // ---- Prompt W11: draft mode -- the chips (O2 / O3), the guide, Add my team ID, Rebuild ----------------------------------
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideFromChip, setGuideFromChip] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const rebuildOpener = useRef<HTMLElement | null>(null);
  const rebuilt = useCallback(() => {
    reloadDraft();
    setMsgs((m) => [...finishReveal(m), { kind: "system", key: key("s"), variant: "rebuilt" }]);
  }, [reloadDraft]);
  const builder = useDraftBuild(rebuilt);
  const askRebuild = () => {
    rebuildOpener.current = document.activeElement as HTMLElement | null;
    setRebuildOpen(true);
  };
  const sentTexts = useMemo(() => msgs.filter((m) => m.kind === "user").map((m) => (m.kind === "user" ? m.text : "")), [msgs]);
  const onDraftChip = useCallback(
    (c: DraftChip) => {
      if (c.action === "guide") {
        setGuideFromChip(true);
        setGuideOpen(true);
      } else {
        send(c.text, c.action === "explain" ? { explain: true } : undefined);
      }
    },
    [send, setGuideOpen, setGuideFromChip],
  );
  const draftFacts = useMemo(
    () => ({ captain: draftData?.captain?.short_name ?? null, left: draftData?.left ?? null, over: draftData?.over ?? null }),
    [draftData],
  );
  // W11h H3: the latest answer's text -- a code-built answer ends with the owner's follow-up, and its chips come first
  const lastAnswer = useMemo(() => {
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m.kind === "assistant" && !m.opening) return m.text;
    }
    return null;
  }, [msgs]);
  const listDraft = useMemo(
    () =>
      isDraftChat
        ? { opening: OPENING_CHIPS, answer: unusedChips(answerChips(draftFacts, lastAnswer), sentTexts, guideFromChip), onChip: onDraftChip }
        : null,
    [isDraftChat, draftFacts, lastAnswer, sentTexts, guideFromChip, onDraftChip],
  );

  const general = ctx?.kind === "general";
  const newRow = isNew && tag ? tag : null;
  const placeholder = ctx?.kind === "team" ? `Ask about ${teamName ?? "your team"}…` : isDraftChat ? "Ask about your draft…" : "Ask anything about FPL…";

  return (
    <div className="ch" data-testid="chat" data-context={ctx?.kind ?? "loading"} data-team-id={teamId ?? ""} data-thread-id={threadId ?? ""} data-ready={opening === "ready"} data-busy={busy}>
      <ChatHeader deadlines={deadlines} now={now} onExpired={onDeadlinesExpired} onMenu={() => setDrawer(true)} isOwner={me.status === "ready" ? me.data.is_owner : null} isAdmin={me.status === "ready" ? me.data.is_admin : null} isGuest={me.status === "ready" ? me.data.is_guest : null} />
      <GuestSession me={me.status === "ready" ? me.data : null} banner />
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
            <h1 data-testid="chat-title">{titleOf(msgs, row, isDraftChat)}</h1>
            {tag && (
              <span className={tag.cls} data-testid="chat-tag">
                {tag.text}
              </span>
            )}
          </div>
          {isDraftChat && (
            <div className="dr-banner" data-testid="draft-banner">
              <span>Not in FPL yet ·</span>
              <button type="button" onClick={() => setGuideOpen(true)} data-testid="draft-banner-guide">
                How to enter it
              </button>
            </div>
          )}
          {narrow && isDraftChat && (
            <MobileDraft draft={draftRes} preview={pending?.preview ?? null} open={panel} onToggle={() => setPanel((p) => !p)} onRebuild={askRebuild} onRetry={reloadDraft} rebuilding={builder.state === "building"} />
          )}
          {narrow && ctx?.kind === "team" && (
            <MobileTeam card={card as Parameters<typeof MobileTeam>[0]["card"]} preview={pending?.preview ?? null} open={panel} onToggle={() => setPanel((p) => !p)} refresh={refresh} onRefresh={doRefresh} onRetry={reloadCard} teamName={teamName} />
          )}
          <div className="ch-scroll-wrap">
          <div className="ch-scroll" ref={scroller} onScroll={onThreadScroll} data-testid="thread-scroll">
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
              {isNew && ctx && <EmptyState mode={ctx.kind} teamName={teamName} nextGw={nextGw} card={cardData} firstName={firstName} onChip={chip} draft={draftData} onGuide={() => setGuideOpen(true)} />}
              {msgs.length > 0 && (
                <MessageList msgs={msgs} now={listNow} phone={narrow} onYes={onYes} onNo={onNo} onRetry={retry} onStartNew={newChat} onFeedback={feedback} draft={listDraft} />
              )}
            </div>
          </div>
          {showDown && msgs.length > 0 && (
            <button type="button" className="ch-down" onClick={toBottom} aria-label="Scroll to the end of the chat" data-testid="scroll-down">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 5v14M6 13l6 6 6-6" />
              </svg>
            </button>
          )}
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
        {!narrow && isDraftChat && (
          <div className="ch-right">
            <DraftPanel draft={draftRes} preview={pending?.preview ?? null} open={cardOpen} onToggle={() => setCardOpen((o) => !o)} onRebuild={askRebuild} onRetry={reloadDraft} rebuilding={builder.state === "building"} />
          </div>
        )}
        {!narrow && ctx?.kind === "team" && (
          <div className="ch-right">
            <TeamCardPanel card={card as Parameters<typeof TeamCardPanel>[0]["card"]} preview={pending?.preview ?? null} refresh={refresh} onRefresh={doRefresh} onRetry={reloadCard} open={cardOpen} onToggle={() => setCardOpen((o) => !o)} teamName={teamName} />
          </div>
        )}
      </div>
      {narrow && drawer && <MobileDrawer onClose={() => setDrawer(false)} onNew={newChat} threads={threads} currentId={threadId} newRow={newRow} now={now} onOpen={openThread} onDelete={askDelete} />}
      {isDraftChat && (
        <>
          <EnterGuide
            d={draftData}
            open={guideOpen}
            onClose={() => setGuideOpen(false)}
            onAddTeam={() => {
              setGuideOpen(false);
              setAddOpen(true);
            }}
          />
          <AddTeamDialog
            open={addOpen}
            onOpenChange={setAddOpen}
            onAdded={(c) => toast.success(`${c.label ?? c.entry_name ?? "Your team"} added`, { description: ADD_COPY.success, duration: 8000 })}
          />
          <RebuildConfirm open={rebuildOpen} onClose={() => setRebuildOpen(false)} onConfirm={builder.rebuild} returnTo={rebuildOpener} />
          <BuildingDialog open={builder.state === "building"} rebuild />
          <BuildFailedDialog open={builder.state === "failed"} onCancel={builder.cancel} onRetry={builder.retry} />
        </>
      )}
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
