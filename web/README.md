# FPL Copilot — website (`web/`)

Next.js (App Router, TypeScript) + Tailwind CSS + shadcn/ui + Clerk, built from the approved Claude Design handoff
("True colour", BRIEF.md). The Python backend lives one level up and is unchanged by this folder.

## Run it on the laptop

```
cd C:\dev\fpl-copilot\web
npm install
npm run dev
```

Open http://localhost:3000/login. The backend call on `/teams` needs the API running in clerk mode:

```
cd C:\dev\fpl-copilot
$env:AUTH_MODE='clerk'; $env:CORS_ALLOWED_ORIGINS='http://localhost:3000'; $env:CLERK_AUTHORIZED_PARTIES='http://localhost:3000'
uv run uvicorn main:app --port 8000
```

## Files that are NOT in git

- `.env.local` — `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_API_BASE` (= `http://localhost:8000` on the laptop),
  `NEXT_PUBLIC_CLERK_SIGN_IN_URL=/login`, `NEXT_PUBLIC_CLERK_SIGN_UP_URL=/login`. Optional `SITE_PASSWORD` turns on the
  Basic-Auth site gate (`proxy.ts`); unset = off.
- `public/players/` (the five cut-outs: `vandijk-body/head`, `haaland-body/head`, `ball` as .webp), `public/intro/love-me-again.mp3`
  and `design/` (the unzipped handoff). Copy them in by hand; without the images the page shows the SVG fallback figures,
  without the song it runs silent.

## Scripts

- `npm run dev` / `npm run build` / `npm run start`
- `npm run lint` — ESLint (eslint-config-next)
- `npm run typecheck` — `tsc --noEmit`
- `npm run e2e` — Playwright against a running `npm run dev` (Chromium via the installed Microsoft Edge, no browser download)

## Layout

- `app/login/` — the page (`page.tsx` + `login.css` keyframes), `components/login/` — LoginExperience (intro auto-starts; the song
  tries to play on load and otherwise starts on the first interaction; the header button mutes, remembered), IntroOverlay,
  PlayerStage, SignInCard
- `app/sso-callback/` — Google OAuth return, `app/teams/` — protected placeholder that calls `GET /me` on the API
- `proxy.ts` — Clerk + optional site password
