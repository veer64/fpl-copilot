"use client";

import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, deadlinesPublic, type TeamCard } from "@/lib/api";
import { nextEvent } from "@/lib/time";
import { useNow, useResource } from "@/components/home/useResource";
import { Arrow, Backdrop, PublicFooter, PublicHeader } from "./PublicChrome";

/** /about (Prompt W5): the marketing page, ported from about-desktop / about-mobile. Public. Wording as approved at the W5
 *  checkpoint (A5, A6, A9, A11). The example chat card is mock data on purpose (static). The JUST ASK chips: signed out ->
 *  /login; signed in -> a team question goes to /chat?team={last-used team}&q=... when the visitor has a team, else
 *  /chat?q=...; a general question to /chat?q=... (prefilled, not sent). "GW{n}" is the next deadline's gameweek, read from
 *  the open /deadlines (no token). */

const CONTACT = "veersanghavi8@gmail.com";

const FEATURES: { title: string; text: string; icon: React.ReactNode }[] = [
  {
    title: "Nail your captain pick",
    text: "Compare your options on predicted points and fixtures — and hand the armband to the right player.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="8" width="18" height="8" rx="2" />
        <path d="M10.5 10.5a2 2 0 1 0 0 3M13.5 10v4" />
      </svg>
    ),
  },
  {
    title: "Make smarter transfers",
    text: "Get the best move for your bank and free transfers, before the deadline sneaks up.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 8h13l-3-3M20 16H7l3 3" />
      </svg>
    ),
  },
  {
    title: "Know who’s really fit",
    text: "Injury flags and the latest club news — with the source and date shown.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l9 16H3z" />
        <path d="M12 10v4M12 17h.01" />
      </svg>
    ),
  },
  {
    title: "See the points coming",
    text: "Predicted points for your squad, refreshed before each deadline.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </svg>
    ),
  },
  {
    title: "Your team, on the pitch",
    text: "Your XI, bench, captain and chips in one view — hover or tap any player for the key numbers.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M3 12h18" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    ),
  },
  {
    title: "Preview every change",
    text: "See who goes out and who comes in before you commit — then make the move in the FPL app.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M5 12l5 5L20 7" />
      </svg>
    ),
  },
  {
    title: "Up to three teams",
    text: "Main team, mini-league side, a mate’s squad — switch between them from Home.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" />
      </svg>
    ),
  },
  {
    title: "Never miss a deadline",
    text: "The next deadline counts down at the top of Home and every chat.",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    ),
  },
];

/** The six chips; `team` ones go to the visitor's last-used team when they have one. */
export function askChips(gw: string): { text: string; team: boolean }[] {
  return [
    { text: `Who should I captain for ${gw}?`, team: true },
    { text: `What’s my best transfer for ${gw}?`, team: true },
    { text: "Is Saka fit to play?", team: true },
    { text: "Which of my players have the best fixtures?", team: true },
    { text: "Who’s in form right now?", team: false },
    { text: "Best picks of the week?", team: false },
  ];
}

/** The team a chip should open: the most recently used, else the active one, else the first. */
export function lastUsedTeam(cards: TeamCard[]): number | null {
  const used = cards.filter((t) => t.last_used_at).sort((a, b) => (b.last_used_at! > a.last_used_at! ? 1 : -1));
  return used[0]?.fpl_team_id ?? cards.find((t) => t.is_active)?.fpl_team_id ?? cards[0]?.fpl_team_id ?? null;
}

export function chipHref(signedIn: boolean, team: boolean, teamId: number | null, q: string): string {
  if (!signedIn) return "/login";
  const query = encodeURIComponent(q);
  return team && teamId ? `/chat?team=${teamId}&q=${query}` : `/chat?q=${query}`;
}

const Chat = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 5h16v11H9l-5 4z" />
  </svg>
);
const Info = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  </svg>
);
const Hex = ({ size }: { size: number }) => (
  <svg width={size} height={size} viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
    <path d="M14 2 L25 8.5 V19.5 L14 26 L3 19.5 V8.5 Z" />
    <path d="M9 17 L14 11 L19 17" />
  </svg>
);

const noTeams = () => Promise.resolve<TeamCard[]>([]);

export function AboutExperience() {
  const { isLoaded, isSignedIn } = useAuth();
  const signedIn = isLoaded && !!isSignedIn;
  const now = useNow();
  const [nextGw, setNextGw] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    deadlinesPublic()
      .then((d) => {
        if (cancelled) return;
        const next = nextEvent(d.events, new Date());
        setNextGw(next?.gw ?? null);
      })
      .catch(() => undefined); // the chips then say "this gameweek"
    return () => {
      cancelled = true;
    };
  }, []);
  const [teams] = useResource<TeamCard[]>(signedIn ? api.teams : noTeams);
  const teamId = useMemo(() => (teams.status === "ready" ? lastUsedTeam(teams.data) : null), [teams]);
  const gw = nextGw ? `GW${nextGw}` : "this gameweek";
  const primary = signedIn ? { href: "/home", text: "Ask your first question" } : { href: "/login", text: "Sign in to start" };
  void now;

  return (
    <div className="pp" data-testid="about" data-signed-in={isLoaded ? signedIn : "loading"} data-next-gw={nextGw ?? ""}>
      <Backdrop page="about" />
      <PublicHeader />

      <div className="pp-hero">
        <div className="pp-hero-text">
          <span className="pp-eyebrow">ABOUT FPL COPILOT</span>
          <h1>Outsmart your mini-league with an AI that knows the data.</h1>
          <p className="pp-p pp-hero-sub">
            FPL Copilot is your AI assistant for Fantasy Premier League. Ask about players, captains, transfers and your own team — and get answers built on real data, not hunches.
          </p>
          <div className="pp-hero-cta">
            <a href={primary.href} className="pp-btn-p" data-testid="hero-primary">
              {primary.text}
              <Arrow />
            </a>
            <a href="#features" className="pp-btn-s" data-testid="hero-secondary">
              See what it does
            </a>
          </div>
        </div>
        <div className="pp-example-wrap">
          <div className="hm-glass pp-example" aria-label="Example conversation" data-testid="example-chat">
            <span className="hm-br hm-tl" aria-hidden="true" />
            <span className="hm-br hm-brr" aria-hidden="true" />
            <div className="pp-example-top">
              <span className="pp-example-lbl">EXAMPLE</span>
              <span className="pp-tag">VEER’S XI</span>
            </div>
            <div className="pp-example-q">Who should I captain for GW10?</div>
            <div className="pp-example-a">
              <span className="pp-example-av" aria-hidden="true">
                <Hex size={14} />
              </span>
              <div className="pp-example-body">
                <p>
                  <strong>Captain Haaland.</strong> Best fixture and the top predicted score in your XI.
                </p>
                <div className="pp-example-tbl">
                  <div className="head">
                    <span>PLAYER</span>
                    <span>GW10</span>
                    <span>PRED.</span>
                  </div>
                  <div className="best">
                    <b>Haaland</b>
                    <span className="mono">BOU (H)</span>
                    <b className="cyan">7.8</b>
                  </div>
                  <div>
                    <b>Salah</b>
                    <span className="mono">AVL (H)</span>
                    <span>6.4</span>
                  </div>
                </div>
                <span className="pp-example-src">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M4 4h12l4 4v12H4z" />
                    <path d="M8 12h8M8 16h5" />
                  </svg>
                  Club news · 3 Nov
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <main className="pp-main">
        <section id="features" className="pp-sec" aria-labelledby="features-title">
          <div className="pp-sec-head">
            <span className="pp-eyebrow">WHAT IT HELPS YOU WITH</span>
            <h2 id="features-title" className="pp-h2">
              Every decision before the deadline, sorted.
            </h2>
          </div>
          <div className="pp-tiles" data-testid="feature-tiles">
            {FEATURES.map((f) => (
              <div className="hm-glass pp-tile" key={f.title}>
                <span className="pp-ic lg" aria-hidden="true">
                  {f.icon}
                </span>
                <b>{f.title}</b>
                <span className="d">{f.text}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="pp-sec" aria-labelledby="ask-title">
          <div className="hm-glass pp-ask">
            <span className="hm-br hm-tl" aria-hidden="true" />
            <span className="hm-br hm-brr" aria-hidden="true" />
            <div aria-hidden="true" className="pp-ask-glow" />
            <div className="pp-ask-head">
              <span className="pp-eyebrow">JUST ASK</span>
              <h2 id="ask-title" className="pp-h2">
                Ask it like you’d ask your mate who never misses a press conference.
              </h2>
            </div>
            <div className="pp-chips" data-testid="ask-chips">
              {askChips(gw).map((c) => (
                <a href={chipHref(signedIn, c.team, teamId, c.text)} className="pp-chip" key={c.text} data-testid="ask-chip" data-team={c.team}>
                  <Chat />
                  {c.text}
                </a>
              ))}
            </div>
          </div>
        </section>

        <section className="pp-sec pp-two" aria-label="The fine print and who made it">
          <div className="hm-glass pp-box" data-testid="fine-print">
            <span className="pp-eyebrow" style={{ color: "#FFC23D" }}>
              THE FINE PRINT
            </span>
            <ul className="pp-fine">
              <li>
                <span>
                  <Info />
                </span>
                <span>
                  <strong>Predictions are estimates</strong> — not certainties.
                </span>
              </li>
              <li>
                <span>
                  <Info />
                </span>
                <span>
                  <strong>Your FPL team is as of the last deadline</strong> — FPL makes picks public only then. Tap Refresh after a deadline to update it; transfers made since aren’t seen yet.
                </span>
              </li>
              <li>
                <span>
                  <Info />
                </span>
                <span>
                  <strong>“Yes, apply” stays inside FPL Copilot</strong> — it changes our saved copy of your squad, never your real FPL team.
                </span>
              </li>
              <li>
                <span>
                  <Info />
                </span>
                <span>
                  <strong>Not betting advice</strong> — it’s for playing Fantasy Premier League.
                </span>
              </li>
            </ul>
            <div className="pp-indep">
              <span>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" />
                  <path d="M8.5 12l2.5 2.5 4.5-5" />
                </svg>
              </span>
              <span>FPL Copilot is an independent project, not affiliated with or endorsed by the Premier League or Fantasy Premier League.</span>
            </div>
          </div>
          <div className="hm-glass pp-box made" data-testid="made-by">
            <span className="pp-eyebrow">MADE BY</span>
            <div className="pp-made-who">
              <span className="hm-avatar" aria-hidden="true">
                VS
              </span>
              <div>
                <b>Veer Sanghavi</b>
                <span>Built FPL Copilot.</span>
              </div>
            </div>
            <div className="pp-links">
              <a className="pp-lk" href={`mailto:${CONTACT}`}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <path d="M3 7l9 6 9-6" />
                </svg>
                Email
              </a>
              <a className="pp-lk" href="https://www.linkedin.com/in/veer-sanghavi" target="_blank" rel="noreferrer">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
                  <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
                </svg>
                LinkedIn
              </a>
              <a className="pp-lk" href="https://github.com/veer64" target="_blank" rel="noreferrer">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 4l-4 16" />
                </svg>
                GitHub
              </a>
              <a className="pp-lk" href="https://veer-sanghavi-64.vercel.app/" target="_blank" rel="noreferrer">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
                </svg>
                Website
              </a>
            </div>
          </div>
        </section>

        <section className="pp-sec" aria-labelledby="closing-title">
          <div className="pp-closing">
            <span className="hm-br hm-tl" aria-hidden="true" />
            <span className="hm-br hm-brr" aria-hidden="true" />
            <h2 id="closing-title" className="pp-h2">
              The next deadline is coming.
            </h2>
            <p className="pp-p">Get your squad sorted before it does.</p>
            <a href={primary.href} className="pp-btn-p" data-testid="closing-primary">
              {primary.text}
              <Arrow />
            </a>
          </div>
        </section>
      </main>
      <PublicFooter page="about" />
    </div>
  );
}
