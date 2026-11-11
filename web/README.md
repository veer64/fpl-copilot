# FPL Copilot — website (`web/`)

Next.js (App Router, TypeScript) + Tailwind CSS + shadcn/ui + Clerk, built from the approved Claude Design handoff
("True colour", BRIEF.md). The Python backend lives one level up and is unchanged by this folder.

## Run it on the laptop

```
cd C:\dev\fpl-copilot\web
npm install
npm run dev
```

Open http://localhost:3000/login. Sign in lands on `/home`, and everything on it (teams, recent chats, the deadline) comes from
the API, which must be running in clerk mode:

```
cd C:\dev\fpl-copilot
$env:AUTH_MODE='clerk'; $env:CORS_ALLOWED_ORIGINS='http://localhost:3000'; $env:CLERK_AUTHORIZED_PARTIES='http://localhost:3000'
uv run python -m uvicorn main:app --port 8000
```

(`python -m uvicorn`, not the `uvicorn` shim: the shim in `.venv/Scripts` points at an old interpreter.)

## Files that are NOT in git

- `.env.local` — `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_API_BASE` (= `http://localhost:8000` on the laptop),
  `NEXT_PUBLIC_CLERK_SIGN_IN_URL=/login`, `NEXT_PUBLIC_CLERK_SIGN_UP_URL=/login`. Optional `SITE_PASSWORD` turns on the
  Basic-Auth site gate (`proxy.ts`); unset = off.
- `public/players/` (the five cut-outs: `vandijk-body/head`, `haaland-body/head`, `ball` as .webp), `public/music/*.mp3` (the shuffled background music, Prompt W5b; the list in `lib/music-tracks.ts`)
  and `design/` (the unzipped login handoff). Copy them in by hand; without the images the page shows the SVG fallback figures,
  without the song it runs silent.
- `public/images/home-bg.webp` (the Home page's background photo) and `design-handoff/home/` (the unzipped Home handoff:
  BRIEF.md, the two references, the photo). Copy `design-handoff/home/images/home-bg.webp` to `public/images/`.

## Scripts

- `npm run dev` / `npm run build` / `npm run start`
- `npm run lint` — ESLint (eslint-config-next)
- `npm run typecheck` — `tsc --noEmit`
- `npm run e2e` — Playwright against a running `npm run dev` (Chromium via the installed Microsoft Edge, no browser download);
  `e2e/home-journey.spec.ts` and the two chat specs need the API in clerk mode (`W4_API_BASE`, default :8000) and read FPL for
  the team ids; the chat specs spend real agent turns
- `node scripts/contrast_home.mjs` — the Home page's contrast table
- `node scripts/contrast_public.mjs` — the About / Privacy pages' and the delete dialogs' contrast table (Prompt W5);
  `--live http://localhost:3002` adds the computed-colour sweep of every button and button-styled link on the signed-out pages
  (Prompt W5b: the static table cannot see a cascade accident; `scripts/lib/sweep.mjs` reads what the browser painted; the
  signed-in pages are swept by `e2e/w5b-music.spec.ts`), `--selftest` proves the sweep fails the W5b case on a fixture;
  `node scripts/render_references_w5.mjs` — the five W5 references rendered beside the journey's screenshots

## Layout

- `app/login/` — the page (`page.tsx` + `login.css` keyframes), `components/login/` — LoginExperience (intro auto-starts; the
  music is the site's MusicProvider since Prompt W5b: volume 1 during the intro, 35 % on login; the header button is the shared
  MusicButton), IntroOverlay, PlayerStage, SignInCard
- `app/sso-callback/` — Google OAuth return
- `app/home/` (+ `home.css`), `components/home/` — the Home page (Prompt W3, "Command Deck"): HomeExperience (GET /me/teams,
  /threads, /deadlines with the browser's Clerk token; every action opens the Chat page), HomeHeader (deadline pill, account
  menu), TeamCard / AddTeamDialog (Dialog on desktop, Drawer on phones; ID or pasted link; the helper), GeneralCard /
  RecentChats, Skeletons, ErrorBox
- `app/chat/` (+ `chat.css`), `components/chat/` — the Chat page (Prompt W4): ChatExperience (`/chat` General, `/chat?team=`
  Team, `/chat?q=` prefilled and not sent, `/chat/{id}` a past chat in its own team; the team is activated on SEND, never on
  open), ChatHeader (Home's deadline pill — its `compact` variant on phones — and account menu), Sidebar / MobileDrawer (past
  chats TODAY / YESTERDAY / EARLIER, collapse in localStorage), Messages (Markdown via react-markdown + remark-gfm: tables with
  the bold "best row"; Sources chips + pop-up; Copy; thumbs -> POST /messages/{id}/feedback), PreviewCard (the squad-change
  preview: Yes / No send "Yes" / "No"), Thinking (spinner words from `lib/spinner-words.ts`, the only place the list lives),
  SystemMessage (daily limit a, 429 b, 409 c, anything else d), Composer (2,000 characters, the counter from 1,800, the disabled
  texts), EmptyState, TeamCardPanel / Pitch (GET /me/teams/{id}/card: the pitch with every OUT / IN of a pending preview, the
  hover card, bench, chips, freshness footer, the three problem states), MobileTeam (team bar, pitch panel, player sheet)
- `lib/clubs.ts` — the 20 clubs' codes and strip colours (`node scripts/contrast_clubs.mjs`); `lib/sources.ts` — hides the text
  "Sources" block only on an exact match of the server's shape (`node scripts/check_sources_strip.mjs`, fixtures generated by
  `news_search.render_citations`); `node scripts/contrast_chat.mjs` — the Chat page's contrast table
- `e2e/chat-journey.spec.ts` (desktop) and `e2e/chat-mobile.spec.ts` (phone) — real backend in clerk mode + real agent turns;
  `e2e/w4.ts` the shared helpers
- `app/about/`, `app/privacy/` (+ `app/public-pages.css`), `components/public/` — the public About and Privacy pages (Prompt W5):
  PublicChrome (the header switches on the Clerk session: "Sign in" / "← Home" + the account menu; the footer; the backdrop
  photo fixed from 1024px, absolute below), AboutExperience (the JUST ASK chips: signed out -> /login, signed in -> /chat?team=
  {last-used team}&q=... or /chat?q=...; "GW{n}" from the open `/deadlines`), PrivacyExperience (the sticky "ON THIS PAGE" list
  with aria-current, section chips on phones, `PRIVACY_UPDATED` the one "Last updated" constant)
- `components/account/` — ConfirmDelete (the shared destructive confirm: Dialog on desktop, bottom sheet on phones; focus starts
  on Cancel; cannot close while deleting; the inline alert + "Try again") and DeleteAccountDialog (DELETE /me -> the one-time
  note queued for /login in sessionStorage -> Clerk sign-out). HomeHeader's AccountMenu is the ONE menu every page imports:
  Sign out, a divider, Delete account (disabled until /me answers; disabled with the owner note for user 1). Delete chat (the
  trash on a past-chat row -> DELETE /threads/{id}) and Remove team (the trash on a Home card -> DELETE /me/teams/{id}) use
  the same confirm
- `e2e/w5-journey.spec.ts` (desktop) and `e2e/w5-mobile.spec.ts` (phone) — the W5 journey against the scratchpad backend
  wrapper (clerk mode, :8010, FPL counted, a test-only Clerk-failure switch); `e2e/w5.ts` its helpers
- `components/music/` + `lib/music-tracks.ts` — the site-wide background music (Prompt W5b): MusicProvider in the root layout owns
  the ONE audio element (it keeps playing across every client navigation), shuffles the list (a visit never starts on the previous
  visit's track; every track plays before a repeat), resumes the same track after a full page load (sessionStorage), starts on
  the first click or key when autoplay is blocked, and pauses + drops the source when muted (the existing `fpl-sound` choice);
  MusicButton is the mute control every header shows next to the account button (Login, Home, Chat, About, Privacy). The track
  list lives ONLY in `lib/music-tracks.ts`; the files in `public/music/` are gitignored and re-encoded to 128 kbps / -16 LUFS.
  `e2e/w5b-music.spec.ts` (the CTA fix, the sweep, the music) and `e2e/w5b-regression.spec.ts` (the W5 deletes on seeded rows)
- `lib/api.ts` — the API client and types (one in-flight promise per GET path; a 90 s timeout on /chat), `parseTeamInput`;
  `lib/time.ts` — greeting, time ago, deadline words
- `/teams` redirects to `/home`; a signed-in visit to `/login` goes to `/home`
- `proxy.ts` — Clerk + optional site password
