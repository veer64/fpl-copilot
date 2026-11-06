"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { toast } from "sonner";
import { ApiError, api, type TeamCard as Card } from "@/lib/api";
import { greetingWord, nextEvent } from "@/lib/time";
import { AddTeamDialog, ADD_COPY } from "./AddTeamDialog";
import { ErrorBox } from "./ErrorBox";
import { BallIcon, Chips, GeneralCard, RecentChats } from "./GeneralCard";
import { DeadlinePill, HomeHeader } from "./HomeHeader";
import { LowerSkeleton, TeamsSkeleton } from "./Skeletons";
import { AddTeamCard, Spinner, TeamCard, teamName } from "./TeamCard";
import { useNow, useResource } from "./useResource";

export const MAX_TEAMS = 3;
const NEW_PULSE_MS = 1500;

/** /home ("Command Deck"): everything on it comes from the backend -- GET /me/teams, GET /threads, GET /deadlines -- with
 *  the browser's Clerk token; the greeting and the account menu from Clerk. Every action opens the Chat page (/chat). */
export function HomeExperience() {
  const router = useRouter();
  const { getToken } = useAuth();
  const { user, isLoaded: userLoaded } = useUser();
  const now = useNow();

  const [teams, reloadTeams] = useResource(api.teams);
  const [threads, reloadThreads] = useResource(api.threads);
  const [deadlines, reloadDeadlines] = useResource(api.deadlines);

  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState<{ kind: "ask" | "refresh"; id: number } | { kind: "general" } | null>(null);
  const [refreshFailed, setRefreshFailed] = useState<Record<number, boolean>>({});
  const [newId, setNewId] = useState<number | null>(null);

  const nextGw = deadlines.status === "ready" && now ? (nextEvent(deadlines.data.events, now)?.gw ?? null) : null;
  const firstName = userLoaded ? user?.firstName || user?.fullName?.split(/\s+/)[0] || null : null;

  const cards = useMemo(() => (teams.status === "ready" ? teams.data : []), [teams]);
  const lastUsedId = useMemo(() => {
    const used = cards.filter((t) => t.last_used_at).sort((a, b) => (b.last_used_at! > a.last_used_at! ? 1 : -1));
    return used[0]?.fpl_team_id ?? cards.find((t) => t.is_active)?.fpl_team_id ?? cards[0]?.fpl_team_id ?? null;
  }, [cards]);

  const loading = teams.status === "loading" || threads.status === "loading";
  const isNew = teams.status === "ready" && threads.status === "ready" && teams.data.length === 0 && threads.data.length === 0;

  // --- actions: every one of them ends on the Chat page -------------------------------------------------------------------
  const ask = async (t: Card) => {
    setBusy({ kind: "ask", id: t.fpl_team_id });
    try {
      await api.activate(getToken, t.fpl_team_id); // the team becomes the active one; its default thread is the chat's
      router.push(`/chat?team=${t.fpl_team_id}`);
    } catch (err) {
      toast.error(`Couldn’t open a chat about ${teamName(t)}: ${err instanceof ApiError ? err.detail : "the API could not be reached"}`);
      setBusy(null);
    }
  };

  const general = async () => {
    setBusy({ kind: "general" });
    try {
      await api.deactivate(getToken); // "not against any team": no team active, a fresh default thread of the user's own
      router.push("/chat");
    } catch (err) {
      toast.error(`Couldn’t start a general chat: ${err instanceof ApiError ? err.detail : "the API could not be reached"}`);
      setBusy(null);
    }
  };

  const chip = (q: string) => router.push(`/chat?q=${encodeURIComponent(q)}`);

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

  const greeting = isNew ? (
    <div className="hm-greet" data-testid="greeting" data-state="new">
      <div>
        <span className="hm-lbl">Welcome</span>
        <h1>Welcome, manager.</h1>
        <p>Add your FPL team for answers about your squad — or just ask a question.</p>
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
        <div aria-hidden="true" className="hm-band" />
        <DeadlinePill deadlines={deadlines} now={now} onExpired={onDeadlinesExpired} band />

        {greeting}

        {teams.status === "error" ? (
          <ErrorBox what="your teams" error={teams.error} onRetry={reloadTeams} />
        ) : teams.status === "loading" ? (
          <TeamsSkeleton />
        ) : isNew ? (
          <>
            <div className="hm-choices" data-testid="new-user-choices">
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
                      "Just ask a question"
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
              <span className="hm-count" data-testid="teams-count">
                {cards.length} of {MAX_TEAMS} teams
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
                />
              ))}
              {cards.length < MAX_TEAMS && <AddTeamCard slotsLeft={MAX_TEAMS - cards.length} onOpen={() => setAddOpen(true)} />}
            </div>
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
          <a href="/privacy">Privacy</a>
          <a href="/about">About</a>
        </footer>
      </div>

      <AddTeamDialog open={addOpen} onOpenChange={setAddOpen} onAdded={added} />
    </div>
  );
}
