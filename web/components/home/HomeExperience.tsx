"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { toast } from "sonner";
import { ApiError, api, type DraftResult, type TeamCard as Card } from "@/lib/api";
import { greetingWord, nextEvent } from "@/lib/time";
import { ConfirmDelete } from "@/components/account/ConfirmDelete";
import { AddTeamDialog, ADD_COPY } from "./AddTeamDialog";
import { ErrorBox } from "./ErrorBox";
import { BallIcon, Chips, GeneralCard, RecentChats } from "./GeneralCard";
import { DeadlinePill, HomeHeader } from "./HomeHeader";
import { LowerSkeleton, TeamsSkeleton } from "./Skeletons";
import { AddTeamCard, Spinner, TeamCard, TeamsFull, teamName } from "./TeamCard";
import { loginSignedOut, useSignedOutRedirect } from "@/lib/session";
import { useNow, useResource } from "./useResource";
import { GuestSession } from "@/components/guest/GuestSession";
import { BuildChoice, BuildPill, DraftHomeCard, SlimAddRow } from "@/components/draft/DraftParts";
import { BuildFailedDialog, BuildingDialog, RebuildConfirm, useDraftBuild } from "@/components/draft/BuildFlow";
import { EnterGuide } from "@/components/draft/EnterGuide";

export const MAX_TEAMS = 3;
const NEW_PULSE_MS = 1500;
// W10: a navigation that has not left Home after this long gives the button back, with an error
const NAV_TIMEOUT_MS = 10_000;

/** /home ("Command Deck"): everything on it comes from the backend -- GET /me/teams, GET /threads, GET /deadlines -- with
 *  the browser's Clerk token; the greeting and the account menu from Clerk. Every action opens the Chat page (/chat). */
export function HomeExperience() {
  const router = useRouter();
  const { getToken } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const now = useNow();
  useSignedOutRedirect();

  const [teams, reloadTeams] = useResource(api.teams);
  const [threads, reloadThreads] = useResource(api.threads);
  const [deadlines, reloadDeadlines] = useResource(api.deadlines);
  const [draftRes, reloadDraft] = useResource(api.draft); // Prompt W11: the draft team (one per account; never a slot)

  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState<{ kind: "ask" | "refresh"; id: number } | { kind: "general" } | { kind: "draft" } | null>(null);
  const [refreshFailed, setRefreshFailed] = useState<Record<number, boolean>>({});
  const [newId, setNewId] = useState<number | null>(null);

  const nextGw = deadlines.status === "ready" && now ? (nextEvent(deadlines.data.events, now)?.gw ?? null) : null;
  const firstName = userLoaded ? user?.firstName || user?.fullName?.split(/\s+/)[0] || null : null;

  const cards = useMemo(() => (teams.status === "ready" ? teams.data : []), [teams]);
  const lastUsedId = useMemo(() => {
    const used = cards.filter((t) => t.last_used_at).sort((a, b) => (b.last_used_at! > a.last_used_at! ? 1 : -1));
    return used[0]?.fpl_team_id ?? cards.find((t) => t.is_active)?.fpl_team_id ?? cards[0]?.fpl_team_id ?? null;
  }, [cards]);

  const loading = teams.status === "loading" || threads.status === "loading" || draftRes.status === "loading";
  const isNew = teams.status === "ready" && threads.status === "ready" && teams.data.length === 0 && threads.data.length === 0;
  const draft = draftRes.status === "ready" ? draftRes.data.draft : null;

  // --- W10: pending states never outlive the page being shown ----------------------------------------------------------------
  // Next keeps a left page mounted but hidden (React Activity) and shows the SAME instance on Back or a Home link, so a
  // button still said "Opening chat…" (disabled) after the round trip. Effects re-run each time the page is shown, so this
  // one clears every pending state on show and on hide; a page restored from the back-forward cache (pageshow persisted)
  // clears too; and a navigation that has not left Home within NAV_TIMEOUT_MS gives the button back with an error.
  const navTimer = useRef<number | null>(null);
  const clearNav = useCallback(() => {
    if (navTimer.current !== null) window.clearTimeout(navTimer.current);
    navTimer.current = null;
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the page was (re)shown: nothing is pending any more
    setBusy(null);
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) {
        clearNav();
        setBusy(null);
      }
    };
    window.addEventListener("pageshow", onShow);
    return () => {
      window.removeEventListener("pageshow", onShow);
      clearNav();
      setBusy(null);
    };
  }, [clearNav]);
  const navigate = (href: string, what: string) => {
    clearNav();
    navTimer.current = window.setTimeout(() => {
      navTimer.current = null;
      setBusy(null);
      toast.error(`Couldn’t open ${what} — try again.`);
    }, NAV_TIMEOUT_MS);
    router.push(href);
  };

  // --- actions: every one of them ends on the Chat page -------------------------------------------------------------------
  const ask = async (t: Card) => {
    setBusy({ kind: "ask", id: t.fpl_team_id });
    try {
      await api.activate(getToken, t.fpl_team_id); // the team becomes the active one; its default thread is the chat's
      navigate(`/chat?team=${t.fpl_team_id}`, `a chat about ${teamName(t)}`);
    } catch (err) {
      toast.error(`Couldn’t open a chat about ${teamName(t)}: ${err instanceof ApiError ? err.detail : "the API could not be reached"}`);
      setBusy(null);
    }
  };

  const general = async () => {
    setBusy({ kind: "general" });
    try {
      await api.deactivate(getToken); // "not against any team": no team active, a fresh default thread of the user's own
      navigate("/chat", "the chat");
    } catch (err) {
      toast.error(`Couldn’t start a general chat: ${err instanceof ApiError ? err.detail : "the API could not be reached"}`);
      setBusy(null);
    }
  };

  const chip = (q: string) => router.push(`/chat?q=${encodeURIComponent(q)}`);

  // --- Prompt W11: the draft team -- Build (the building card, then straight into the chat), Open, Rebuild, Delete, the guide
  const drafted = (r: DraftResult, kind: "build" | "rebuild") => {
    reloadDraft();
    if (kind === "rebuild") {
      toast.success("Draft rebuilt from the best picks.");
      return;
    }
    const tid = r.thread_id ?? r.draft?.thread_id ?? null;
    setBusy({ kind: "draft" });
    navigate(tid ? `/chat/${tid}` : "/chat?draft=1", "your draft");
  };
  const builder = useDraftBuild(drafted);
  const openDraft = () => {
    if (!draft) return;
    setBusy({ kind: "draft" });
    navigate(draft.thread_id ? `/chat/${draft.thread_id}` : "/chat?draft=1", "your draft");
  };
  const [guideOpen, setGuideOpen] = useState(false);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [deletingDraft, setDeletingDraft] = useState(false);
  const draftOpener = useRef<HTMLElement | null>(null);
  const draftChats = threads.status === "ready" ? threads.data.filter((r) => r.is_draft).length : 0;
  const draftIntro =
    draftChats === 0
      ? "Your 15 players and every change you made will be removed."
      : `Your 15 players, every change you made and its ${draftChats === 1 ? "1 chat" : `${draftChats} chats`} will be removed.`;
  const confirmDeleteDraft = async () => {
    try {
      await api.deleteDraft(getToken);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) loginSignedOut(router);
      throw err;
    }
    setDeletingDraft(false);
    reloadDraft();
    reloadThreads();
  };
  const remember = () => {
    draftOpener.current = document.activeElement as HTMLElement | null;
  };
  const draftActions = {
    onChat: openDraft,
    onGuide: () => {
      remember();
      setGuideOpen(true);
    },
    onRebuild: () => {
      remember();
      setRebuildOpen(true);
    },
    onDelete: () => {
      remember();
      setDeletingDraft(true);
    },
    busy: busy !== null || builder.state === "building",
  };

  const refresh = async (t: Card) => {
    setBusy({ kind: "refresh", id: t.fpl_team_id });
    try {
      await api.refresh(getToken, t.fpl_team_id);
      setRefreshFailed((m) => ({ ...m, [t.fpl_team_id]: false }));
      toast.success(`${teamName(t)} refreshed from FPL`);
      reloadTeams();
    } catch {
      setRefreshFailed((m) => ({ ...m, [t.fpl_team_id]: true }));
    } finally {
      setBusy(null);
    }
  };

  const added = (card: Card) => {
    setNewId(card.fpl_team_id);
    window.setTimeout(() => setNewId(null), NEW_PULSE_MS);
    toast.success(`${teamName(card)} added`, { description: ADD_COPY.success, duration: 8000 });
    reloadTeams();
    reloadThreads();
  };

  const onDeadlinesExpired = useCallback(() => reloadDeadlines(), [reloadDeadlines]);

  // Prompt W5: Remove team -- the trash on a card opens the shared confirm ("its n chats" from /threads); DELETE
  // /me/teams/{id}; the card goes, the Add team slot returns, General mode if it was the active team (the server's doing)
  const [removing, setRemoving] = useState<Card | null>(null);
  const removeOpener = useRef<HTMLElement | null>(null);
  const chatsOf = (t: Card) => (threads.status === "ready" ? threads.data.filter((r) => r.fpl_team_id === t.fpl_team_id).length : 0);
  const removeIntro = (t: Card) => {
    const n = chatsOf(t);
    const chats = n === 0 ? "" : n === 1 ? " and its 1 chat" : ` and its ${n} chats`;
    return `This removes the team, its saved squads${chats} from FPL Copilot. Your real FPL team isn’t affected.`;
  };
  const confirmRemove = async () => {
    if (!removing) return;
    const t = removing;
    try {
      await api.removeTeam(getToken, t.fpl_team_id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) loginSignedOut(router);
      throw err;
    }
    setRemoving(null);
    reloadTeams();
    reloadThreads();
  };

  const greeting = isNew ? (
    <div className="hm-greet" data-testid="greeting" data-state="new">
      <div>
        <span className="hm-lbl">Welcome</span>
        <h1>Welcome, manager.</h1>
        <p>Add your FPL team, build one from our predictions — or just ask a question.</p>
      </div>
    </div>
  ) : (
    <div className="hm-greet" data-testid="greeting" data-state={loading ? "loading" : "returning"}>
      <div>
        <span className="hm-lbl">Home</span>
        <h1>
          {now ? greetingWord(now) : "Hello"}, {firstName ?? "manager"}.
          <br />
          What are we scouting?
        </h1>
        <p>Pick a team to ask about — or ask anything.</p>
      </div>
    </div>
  );

  return (
    <div className="hm" data-testid="home" data-state={loading ? "loading" : isNew ? "new" : "returning"}>
      {/* eslint-disable-next-line @next/next/no-img-element -- the design's background photo, masked; decorative */}
      <img src="/images/home-bg.webp" alt="" aria-hidden="true" className="hm-photo" />
      <div aria-hidden="true" className="hm-glow" />
      <div aria-hidden="true" className="hm-grid" />

      <div className="hm-col">
        <HomeHeader deadlines={deadlines} now={now} onExpired={onDeadlinesExpired} />
        <GuestSession banner />
        <div aria-hidden="true" className="hm-band" />
        <DeadlinePill deadlines={deadlines} now={now} onExpired={onDeadlinesExpired} band />

        {greeting}

        {teams.status === "error" ? (
          <ErrorBox what="your teams" error={teams.error} onRetry={reloadTeams} />
        ) : teams.status === "loading" ? (
          <TeamsSkeleton />
        ) : isNew ? (
          <>
            <div className="hm-choices three" data-testid="new-user-choices">
              <section className="hm-glass hm-choice primary" aria-labelledby="choice-team">
                <span className="hm-br hm-tl" aria-hidden="true" />
                <span className="hm-br hm-brr" aria-hidden="true" />
                <span className="hm-add-plus" aria-hidden="true">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                </span>
                <h2 id="choice-team">Add my FPL team</h2>
                <p>Paste your FPL team ID or the link to your team. We fetch your squad, points and rank from FPL.</p>
                <div className="hm-team-cta">
                  <button type="button" className="hm-btn-p" onClick={() => setAddOpen(true)} data-testid="choice-add-team">
                    Add my FPL team
                  </button>
                </div>
              </section>
              <BuildChoice d={draft} busy={busy !== null || builder.state === "building"} onBuild={builder.build} onOpen={openDraft} />
              <section className="hm-glass hm-choice" aria-labelledby="choice-ask">
                <span className="hm-br hm-tl" aria-hidden="true" />
                <span className="hm-br hm-brr" aria-hidden="true" />
                <span className="hm-gen-icon" aria-hidden="true">
                  <BallIcon />
                </span>
                <h2 id="choice-ask">Just ask a question</h2>
                <p>Player form, who to buy, captaincy, fixtures — no team needed.</p>
                <div className="hm-team-cta">
                  <button type="button" className="hm-btn-o" onClick={general} disabled={busy !== null} data-testid="choice-general" style={{ width: "100%", justifyContent: "center" }}>
                    {busy?.kind === "general" ? (
                      <>
                        <Spinner /> Opening chat…
                      </>
                    ) : (
                      "Start a general chat"
                    )}
                  </button>
                </div>
              </section>
            </div>
            <section className="hm-glass hm-gen wide" aria-label="Example questions" style={{ gridColumn: "auto" }}>
              <span className="hm-br hm-tl" aria-hidden="true" />
              <span className="hm-br hm-brr" aria-hidden="true" />
              <Chips nextGw={nextGw} onChip={chip} />
            </section>
          </>
        ) : (
          <section className="hm-sec" aria-labelledby="teams-title" data-testid="teams-section">
            <div className="hm-sec-head">
              <h2 id="teams-title" className="hm-lbl">
                Your teams
              </h2>
              <span className="dr-head-r">
                {!draft && draftRes.status === "ready" && <BuildPill onBuild={builder.build} busy={busy !== null || builder.state === "building"} />}
                <span className="hm-count" data-testid="teams-count">
                  {cards.length} of {MAX_TEAMS} teams{draft ? " · 1 draft" : ""}
                </span>
              </span>
            </div>
            <div className="hm-teams">
              {cards.map((t) => (
                <TeamCard
                  key={t.fpl_team_id}
                  team={t}
                  lastUsed={t.fpl_team_id === lastUsedId}
                  now={now}
                  isNew={t.fpl_team_id === newId}
                  busy={busy && "id" in busy && busy.id === t.fpl_team_id ? busy.kind : null}
                  refreshFailed={!!refreshFailed[t.fpl_team_id]}
                  onAsk={() => ask(t)}
                  onRefresh={() => refresh(t)}
                  onRemove={() => {
                    removeOpener.current = document.activeElement as HTMLElement | null;
                    setRemoving(t);
                  }}
                />
              ))}
              {draft && cards.length < MAX_TEAMS && <DraftHomeCard d={draft} layout="card" {...draftActions} />}
              {draft ? (
                cards.length < MAX_TEAMS - 1 && <AddTeamCard slotsLeft={MAX_TEAMS - cards.length} onOpen={() => setAddOpen(true)} />
              ) : cards.length < MAX_TEAMS ? (
                <AddTeamCard slotsLeft={MAX_TEAMS - cards.length} onOpen={() => setAddOpen(true)} />
              ) : (
                <TeamsFull max={MAX_TEAMS} />
              )}
            </div>
            {draft && cards.length === MAX_TEAMS - 1 && <SlimAddRow slotsLeft={1} onOpen={() => setAddOpen(true)} />}
            {draft && cards.length >= MAX_TEAMS && <DraftHomeCard d={draft} layout="row" {...draftActions} />}
          </section>
        )}

        {!isNew &&
          (threads.status === "error" ? (
            <ErrorBox what="your recent chats" error={threads.error} onRetry={reloadThreads} />
          ) : threads.status === "loading" ? (
            <LowerSkeleton />
          ) : (
            <div className="hm-lower">
              <GeneralCard nextGw={nextGw} wide={threads.data.length === 0} busy={busy?.kind === "general"} onGeneral={general} onChip={chip} />
              {threads.data.length > 0 && <RecentChats threads={threads.data} now={now} />}
            </div>
          ))}

        <footer className="hm-foot">
          <Link href="/privacy">Privacy</Link>
          <Link href="/about">About</Link>
        </footer>
      </div>

      <AddTeamDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdded={added}
        draftLink={draftRes.status !== "ready" ? null : draft ? { kind: "open", onClick: openDraft } : { kind: "build", onClick: builder.build }}
      />
      <BuildingDialog open={builder.state === "building"} />
      <BuildFailedDialog open={builder.state === "failed"} onCancel={builder.cancel} onRetry={builder.retry} />
      <RebuildConfirm open={rebuildOpen} onClose={() => setRebuildOpen(false)} onConfirm={builder.rebuild} returnTo={draftOpener} />
      <EnterGuide
        d={draft}
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
        onAddTeam={() => {
          setGuideOpen(false);
          setAddOpen(true);
        }}
      />
      <ConfirmDelete
        open={deletingDraft}
        onClose={() => setDeletingDraft(false)}
        title="Delete your draft?"
        intro={draftIntro}
        warning="This can’t be undone."
        confirmLabel="Delete draft"
        busyLabel="Deleting…"
        errorFor={() => "Couldn’t delete your draft — try again."}
        onConfirm={confirmDeleteDraft}
        returnTo={draftOpener}
        role="alertdialog"
        testId="delete-draft"
      />
      <ConfirmDelete
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={`Remove ${removing ? teamName(removing) : "this team"}?`}
        intro={removing ? removeIntro(removing) : ""}
        warning="This can’t be undone."
        confirmLabel="Remove team"
        busyLabel="Removing…"
        errorFor={() => "Couldn’t remove this team — try again."}
        onConfirm={confirmRemove}
        returnTo={removeOpener}
        testId="remove-team"
      />
    </div>
  );
}
