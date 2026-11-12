"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Arrow, Backdrop, PublicFooter, PublicHeader } from "./PublicChrome";

/** /privacy (Prompt W5): the reading page, ported from privacy-desktop / privacy-mobile. Public. Wording as approved at the
 *  W5 checkpoint (P1, P2, P3, P5, P12, P13/14, P15 + the Backups item, P18, P20, P22, C5). The sticky "ON THIS PAGE" list
 *  highlights the section in view (IntersectionObserver, aria-current); the phone shows the sections as a row of chips.
 *  "Last updated" comes from the one constant below. No delete button here: the account menu has it. */

export const PRIVACY_UPDATED = "12 Nov 2026"; // W9: the guest section
const CONTACT = "veersanghavi8@gmail.com";

export const SECTIONS: { id: string; n: string; title: string }[] = [
  { id: "keep", n: "01", title: "What we keep" },
  { id: "never", n: "02", title: "What we never do" },
  { id: "who", n: "03", title: "Who handles it for us" },
  { id: "cookies", n: "04", title: "Cookies" },
  { id: "how-long", n: "05", title: "How long we keep it" },
  { id: "delete", n: "06", title: "Delete your data" },
  { id: "guest", n: "07", title: "Guest mode" }, // W9
  { id: "contact", n: "08", title: "Contact" },
];

const PROVIDERS: [string, string][] = [
  ["Clerk", "Sign-in."],
  ["Google", "Only if you sign in with Google."],
  ["Anthropic", "Writes the answers — your messages are sent to it."],
  ["Voyage AI", "News search — only the search words for a news lookup."],
  ["Langfuse", "Monitoring of how answers are produced. Your questions are hidden; the answers and the data looked up are kept, with emails and phone numbers masked, under an account number — not your name or email."],
  ["Fantasy Premier League", "We fetch your team’s public data by its ID."],
  ["DigitalOcean", "Our server and database."],
  ["Vercel", "Hosts the website."],
];

function Ic({ kind, children }: { kind?: "green" | "coral"; children: React.ReactNode }) {
  return (
    <span className={`pp-ic${kind ? ` ${kind}` : ""}`} aria-hidden="true">
      {children}
    </span>
  );
}
const Clock = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);

/** The section in view: the last section whose top is above the 35% line, by scroll position (an IntersectionObserver is
 *  the trigger); at the very bottom of the page the last section. A clicked entry stays current until the visitor scrolls
 *  themselves (wheel, touch, keys): the sections near the end cannot reach the top of a tall viewport. */
export function useCurrentSection(ids: string[]): [string, (id: string) => void] {
  const [current, setCurrent] = useState(ids[0]);
  const pinned = useRef<string | null>(null);
  useEffect(() => {
    const els = ids.map((id) => document.getElementById(id)).filter((el): el is HTMLElement => !!el);
    if (!els.length) return;
    const pick = () => {
      if (pinned.current) return;
      const line = window.innerHeight * 0.35;
      let best = els[0].id;
      for (const el of els) if (el.getBoundingClientRect().top <= line) best = el.id;
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) best = els[els.length - 1].id;
      setCurrent((c) => (c === best ? c : best));
    };
    const unpin = () => {
      pinned.current = null;
      pick();
    };
    const io = new IntersectionObserver(pick, { threshold: [0, 0.25, 0.5, 0.75, 1] });
    for (const el of els) io.observe(el);
    window.addEventListener("scroll", pick, { passive: true });
    for (const ev of ["wheel", "touchmove", "keydown"] as const) window.addEventListener(ev, unpin, { passive: true });
    pick();
    return () => {
      io.disconnect();
      window.removeEventListener("scroll", pick);
      for (const ev of ["wheel", "touchmove", "keydown"] as const) window.removeEventListener(ev, unpin);
    };
  }, [ids]);
  const pin = (id: string) => {
    pinned.current = id;
    setCurrent(id);
  };
  return [current, pin];
}

const IDS = SECTIONS.map((s) => s.id);

export function PrivacyExperience() {
  const { isLoaded, isSignedIn } = useAuth();
  const signedIn = isLoaded && !!isSignedIn;
  const [current, pin] = useCurrentSection(IDS);
  const go = (e: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    e.preventDefault();
    pin(id);
    el.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    window.history.replaceState(null, "", `#${id}`);
  };
  const nav = (cls: string, label: string) => (
    <nav aria-label={label} className={cls}>
      {SECTIONS.map((s) => (
        <a href={`#${s.id}`} key={s.id} aria-current={current === s.id ? "true" : undefined} onClick={(e) => go(e, s.id)} data-testid="toc-link" data-section={s.id}>
          <i>{s.n}</i>
          {s.title}
        </a>
      ))}
    </nav>
  );

  return (
    <div className="pp" data-testid="privacy" data-signed-in={isLoaded ? signedIn : "loading"} data-current={current}>
      <Backdrop page="privacy" />
      <PublicHeader />

      <div className="pp-phero">
        <span className="pp-eyebrow">PRIVACY</span>
        <h1>Your data, in plain words.</h1>
        <p className="pp-p pp-hero-sub">What we keep, who handles it, and how to delete it.</p>
        <div className="pp-phero-pills">
          <span className="pp-pill" data-testid="last-updated">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            Last updated {PRIVACY_UPDATED}
          </span>
        </div>
      </div>
      <div className="pp-chipnav-wrap">{nav("pp-chipnav", "On this page")}</div>

      <div className="pp-pbody">
        <aside className="pp-toc-wrap" data-testid="toc">
          <span className="pp-toc-lbl">ON THIS PAGE</span>
          {nav("pp-toc", "On this page")}
        </aside>
        <main className="pp-pmain">
          <section id="keep" className="pp-psec" aria-labelledby="keep-title">
            <span className="pp-sec-n">01</span>
            <h2 id="keep-title">What we keep</h2>
            <div className="hm-glass pp-rows">
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" />
                  </svg>
                </Ic>
                <div>
                  <b>Your account</b>
                  <span className="d">Your name, email, how you sign in (Google or an email code), and when you joined and were last active.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="3" y="4" width="18" height="16" rx="2" />
                    <path d="M3 12h18" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </Ic>
                <div>
                  <b>Your FPL teams</b>
                  <span className="d">The FPL team IDs you add, the names you give them, their public FPL data, and our saved copy of each squad with the changes you apply.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M4 5h16v11H9l-5 4z" />
                  </svg>
                </Ic>
                <div>
                  <b>Your chats</b>
                  <span className="d">Your questions and the answers, plus what the assistant looked up and worked out for them — like transfer plans and change previews.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M7 11v9H4v-9z" />
                    <path d="M7 11l4-7c1.3 0 2.3 1 2.3 2.3V10h5.2a2 2 0 0 1 2 2.4l-1.3 6A2 2 0 0 1 17.2 20H7" />
                  </svg>
                </Ic>
                <div>
                  <b>Your feedback</b>
                  <span className="d">Thumbs up and thumbs down on answers.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M4 18a8 8 0 1 1 16 0" />
                    <path d="M12 18l4-5" />
                  </svg>
                </Ic>
                <div>
                  <b>Usage</b>
                  <span className="d">How many answers you get, what they cost, and when you hit the daily limit.</span>
                </div>
              </div>
            </div>
          </section>

          <section id="never" className="pp-psec" aria-labelledby="never-title">
            <span className="pp-sec-n">02</span>
            <h2 id="never-title">What we never do</h2>
            <div className="pp-never">
              <div className="hm-glass">
                <Ic kind="green">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M5.6 5.6l12.8 12.8" />
                  </svg>
                </Ic>
                <b>Sell your data</b>
                <span className="d">Not to anyone, ever.</span>
              </div>
              <div className="hm-glass">
                <Ic kind="green">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </Ic>
                <b>Show ads</b>
                <span className="d">There are no ads on FPL Copilot.</span>
              </div>
              <div className="hm-glass">
                <Ic kind="green">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="8" cy="15" r="4" />
                    <path d="M11 12l9-9M16 7l3 3" />
                  </svg>
                </Ic>
                <b>Ask for your FPL password</b>
                <span className="d">We never log into FPL — your team ID is enough.</span>
              </div>
            </div>
          </section>

          <section id="who" className="pp-psec" aria-labelledby="who-title">
            <span className="pp-sec-n">03</span>
            <h2 id="who-title">Who handles it for us</h2>
            <p className="pp-p pp-lead">A few services do part of the work. Each one only gets what it needs for its job.</p>
            <div className="hm-glass pp-provs" data-testid="providers">
              {PROVIDERS.map(([name, text]) => (
                <div className="pp-prov" key={name}>
                  <b>{name}</b>
                  <span>{text}</span>
                </div>
              ))}
            </div>
          </section>

          <section id="cookies" className="pp-psec" aria-labelledby="cookies-title">
            <span className="pp-sec-n">04</span>
            <h2 id="cookies-title">Cookies</h2>
            <div className="hm-glass pp-rows">
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M12 3a9 9 0 1 0 9 9 3 3 0 0 1-3-3 3 3 0 0 1-3-3 3 3 0 0 1-3-3z" />
                    <path d="M8.5 11.5h.01M12 16h.01M15.5 13.5h.01M8 16h.01" />
                  </svg>
                </Ic>
                <div>
                  <b>Only sign-in cookies</b>
                  <span className="d">The ones that keep you signed in. No analytics or advertising cookies.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6" />
                  </svg>
                </Ic>
                <div>
                  <b>Small preferences</b>
                  <span className="d">Your browser remembers little things, like whether the chat sidebar is collapsed or the music is muted.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" />
                  </svg>
                </Ic>
                <div>
                  <b>Guest mode</b>
                  <span className="d">One extra cookie, fpl_guest, marks this browser as a guest and disappears when the browser closes.</span>
                </div>
              </div>
            </div>
          </section>

          <section id="how-long" className="pp-psec" aria-labelledby="how-long-title">
            <span className="pp-sec-n">05</span>
            <h2 id="how-long-title">How long we keep it</h2>
            <div className="hm-glass pp-rows" data-testid="how-long">
              <div className="pp-row">
                <Ic>
                  <Clock />
                </Ic>
                <div>
                  <b>Until you delete your account</b>
                  <span className="d">Everything listed above stays until you delete your account.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <Clock />
                </Ic>
                <div>
                  <b>The monitoring copy</b>
                  <span className="d">Langfuse keeps it under an account number, not your name or email. Deleting your account doesn’t remove it.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <Clock />
                </Ic>
                <div>
                  <b>Backups</b>
                  <span className="d">Our database backups keep a copy for up to 30 days.</span>
                </div>
              </div>
            </div>
          </section>

          <section id="delete" className="pp-psec" aria-labelledby="delete-title">
            <span className="pp-sec-n">06</span>
            <h2 id="delete-title">Delete your data</h2>
            <div className="pp-danger" data-testid="delete-section" data-signed-in={isLoaded ? signedIn : "loading"}>
              <div className="pp-danger-head">
                <Ic kind="coral">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
                  </svg>
                </Ic>
                <div>
                  <b>Delete your account any time</b>
                  <span>
                    {signedIn ? (
                      <>
                        Open your account menu (top right) and choose <strong>Delete account</strong>.
                      </>
                    ) : (
                      <>
                        <Link href="/login" prefetch={false}>Sign in</Link>, then open your account menu (top right) and choose <strong>Delete account</strong>.
                      </>
                    )}{" "}
                    It removes everything below straight away — this can’t be undone. Our backups and the monitoring copy are kept as described in How long we keep it, and usage totals stay without your name.
                  </span>
                </div>
              </div>
              <div className="pp-danger-pills">
                {["Your account", "Your FPL teams", "Saved squads", "Chats", "Feedback"].map((p) => (
                  <span className="pp-pill" key={p}>
                    {p}
                  </span>
                ))}
              </div>
              <span className="pp-danger-mail">
                Can’t sign in? Email <a href={`mailto:${CONTACT}`}>{CONTACT}</a> and we’ll delete it for you.
              </span>
            </div>
          </section>


          <section id="guest" className="pp-psec" aria-labelledby="guest-title">
            <span className="pp-sec-n">07</span>
            <h2 id="guest-title">Guest mode</h2>
            <div className="hm-glass pp-rows" data-testid="guest-section">
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" />
                  </svg>
                </Ic>
                <div>
                  <b>What it is</b>
                  <span className="d">Continue as guest creates a temporary account with no email address of yours.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="4" y="4" width="16" height="16" rx="3" />
                    <path d="M8 10h8M8 14h5" />
                  </svg>
                </Ic>
                <div>
                  <b>What we keep</b>
                  <span className="d">The same as for a signed-in user while the session lasts: your chats, the teams you add and the usage ledger.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <Clock />
                </Ic>
                <div>
                  <b>When it is deleted</b>
                  <span className="d">
                    Everything is deleted about two minutes after you close the last FPL Copilot tab on a computer, or after 30 minutes without a click, key, scroll or touch — whichever comes first. On a phone, switching to another app doesn’t end it; 30 minutes without activity does. You can also end it yourself from the account menu.
                  </span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
                  </svg>
                </Ic>
                <div>
                  <b>What remains</b>
                  <span className="d">Only the anonymous cost line of each answer (model and amount — no text, no link to you), the monitoring copy in Langfuse under a number that no longer exists, and our backups for up to 30 days.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" />
                  </svg>
                </Ic>
                <div>
                  <b>Abuse limit</b>
                  <span className="d">To limit abuse we keep a salted hash of your IP address for 24 hours (three guest sessions a day per address).</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M12 3a9 9 0 1 0 9 9 3 3 0 0 1-3-3 3 3 0 0 1-3-3 3 3 0 0 1-3-3z" />
                    <path d="M8.5 11.5h.01M12 16h.01M15.5 13.5h.01M8 16h.01" />
                  </svg>
                </Ic>
                <div>
                  <b>Cookies</b>
                  <span className="d">One extra cookie, fpl_guest, marks this browser as a guest and disappears when the browser closes.</span>
                </div>
              </div>
              <div className="pp-row">
                <Ic>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 7v10M9.5 9.5h3.5a1.75 1.75 0 0 1 0 3.5H11a1.75 1.75 0 0 0 0 3.5h3.5" />
                  </svg>
                </Ic>
                <div>
                  <b>Spending</b>
                  <span className="d">A guest session can use at most $0.25 of model time (about five answers); guest mode closes for the day when all guests together reach $3.00.</span>
                </div>
              </div>
            </div>
          </section>

          <section id="contact" className="pp-psec" aria-labelledby="contact-title">
            <span className="pp-sec-n">08</span>
            <h2 id="contact-title">Contact</h2>
            <a href={`mailto:${CONTACT}`} className="hm-glass pp-card" data-testid="contact-email">
              <Ic>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <path d="M3 7l9 6 9-6" />
                </svg>
              </Ic>
              <span>
                <b>Questions about your data?</b>
                <span className="cy">{CONTACT}</span>
              </span>
              <Arrow />
            </a>
            <Link href="/about" className="hm-glass pp-card" data-testid="contact-about">
              <Ic>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 11v5M12 8h.01" />
                </svg>
              </Ic>
              <span>
                <b>About FPL Copilot</b>
                <span className="d">How it works and where the data comes from</span>
              </span>
              <Arrow />
            </Link>
          </section>
        </main>
      </div>
      <PublicFooter page="privacy" />
    </div>
  );
}
