# racing-analyzer (frontend)

Next.js 15 (App Router) + React 19 + TypeScript + Tailwind dashboard
for the LT-Analyzer backend. Project overview, architecture, and
deployment guide are in the [repo root README](../README.md).

## Development

```bash
npm install
cp ../.env.example .env.local
# edit .env.local: NEXT_PUBLIC_API_URL=http://localhost:5000,
#                  NEXT_PUBLIC_WS_URL=ws://localhost:5000,
#                  NEXT_PUBLIC_TURNSTILE_SITE_KEY="" (dev soft-pass),
#                  NEXT_PUBLIC_INVITE_REQUIRED=true

npm run dev                    # http://localhost:3000
```

The backend needs to be running on port 5000 separately (`python race_ui.py`
from the project root).

## Production build

```bash
npm run build                  # Next.js production build into .next/
npm start                      # serve the build on port 3000
```

In prod, pm2 wraps `npm start` via `start-frontend.sh`. `NEXT_PUBLIC_*`
vars are baked into the bundle at build time — any change requires a
rebuild + pm2 restart.

## Tests

```bash
npm test                                       # all 77 tests
npm test -- --testPathPatterns=auth            # subset
npm run test:coverage                          # with coverage report
```

See [`../TESTING.md`](../TESTING.md) for the full guide.

## Notable directories

| Path | Purpose |
|---|---|
| `app/` | App Router pages + components |
| `app/components/RaceDashboard/` | Main live view (track switcher, standings, deltas, stint planner, Fleet Tracker kanban) |
| `app/contexts/AuthContext.tsx` | Auth state, CSRF token, `apiFetch` wrapper, Socket.IO user-prefs subscription |
| `app/services/` | `ApiService`, `WebSocketService`, `UserPrefsService`, `SelectedTrackService` |
| `app/login`, `app/register`, `app/verify-email`, `app/forgot-password`, `app/reset-password`, `app/privacy`, `app/terms` | Auth + GDPR pages |
| `app/admin/` | Track / user / alias / invite-code admin |
| `app/data/` | Search + top-teams + cross-track team profile |
| `app/team/[teamName]/` | Per-team page |
| `utils/raceMath.ts` | Client-side delta math (Phase 2) |
| `utils/persistence.ts` | localStorage helpers (legacy + active) |
| `utils/config.ts` | Env-var-driven config (`API_BASE_URL`, `TURNSTILE_SITE_KEY`, etc.) |
| `__tests__/` | Jest tests (auth, phase2, utils, fleet) |
| `.env.production` | Build-time public env vars |
