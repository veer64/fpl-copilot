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
- `public/players/` (the five cut-outs: `vandijk-body/head`, `haaland-body/head`, `ball` as .webp), `public/intro/love-me-again.mp3`
  and `design/` (the unzipped login handoff). Copy them in by hand; without the images the page shows the SVG fallback figures,
  without the song it runs silent.
- `public/images/home-bg.webp` (the Home page's background photo) and `design-handoff/home/` (the unzipped Home handoff:
  BRIEF.md, the two references, the photo). Copy `design-handoff/home/images/home-bg.webp` to `public/images/`.

## Scripts

- `npm run dev` / `npm run build` / `npm run start`
- `npm run lint` — ESLint (eslint-config-next)
- `npm run typecheck` — `tsc --noEmit`
- `npm run e2e` — Playwright against a running `npm run dev` (Chromium via the installed Microsoft Edge, no browser download);
  `e2e/home-journey.spec.ts` needs the API in clerk mode on :8000 and reads FPL for the team ids
- `node scripts/contrast_home.mjs` — the Home page's contrast table

## Layout

- `app/login/` — the page (`page.tsx` + `login.css` keyframes), `components/login/` — LoginExperience (intro auto-starts; the song
  tries to play on load and otherwise starts on the first interaction; the header button mutes, remembered), IntroOverlay,
  PlayerStage, SignInCard
- `app/sso-callback/` — Google OAuth return
- `app/home/` (+ `home.css`), `components/home/` — the Home page (Prompt W3, "Command Deck"): HomeExperience (GET /me/teams,
  /threads, /deadlines with the browser's Clerk token; every action opens the Chat page), HomeHeader (deadline pill, account
  menu), TeamCard / AddTeamDialog (Dialog on desktop, Drawer on phones; ID or pasted link; the helper), GeneralCard /
  RecentChats, Skeletons, ErrorBox
- `app/chat/` — the placeholder for the Chat page (a later prompt): shows the context Home handed over, the thread, the question
- `lib/api.ts` — the API client and types, `parseTeamInput`; `lib/time.ts` — greeting, time ago, deadline words
- `/teams` redirects to `/home`; a signed-in visit to `/login` goes to `/home`
- `proxy.ts` — Clerk + optional site password
