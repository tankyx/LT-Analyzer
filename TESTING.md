# Testing Guide

Both backend (pytest) and frontend (Jest) test suites. CI runs them on
every push via `.github/workflows/tests.yml`.

## Quick start

```bash
# Backend (from project root)
source racing-venv/bin/activate
pytest --no-cov                   # all 123 tests, ~30s
pytest -m unit --no-cov           # unit-level only, ~1s
pytest -m integration --no-cov    # integration (real sqlite), ~25s

# Frontend
cd racing-analyzer
npm test                          # all 57 tests, ~3s
npm test -- --testPathPatterns=auth   # subset
```

## Layout

### Backend (`tests/`)

| Directory | What it covers | Count |
|---|---|---|
| `tests/test_auth/` | Phase 1 — registration, email verification, password reset, login, CSRF guard, audit log, rate limits, gated reads, `/api/auth/me`, ProxyFix, admin invite + audit endpoints | 82 |
| `tests/test_phase2/` | Per-user-per-track prefs CRUD + auth isolation + validation, legacy endpoint removal | 32 |
| `tests/test_phase3/` | TTL query cache + heavy-read rate limit | 8 |
| `tests/test_migrations/` | Phase 1 + 2 schema migration idempotency + duplicate-email guard + FK cascade | 9 |

The shared fixture `tests/test_auth/conftest.py` stands up a real
sqlite-backed Flask test client. `test_phase2/conftest.py` and
`test_phase3/conftest.py` re-export those fixtures so their tests
don't have to duplicate setup.

Markers:
- `@pytest.mark.unit` — no I/O, mocks only (`test_email_service`,
  `test_turnstile`, etc.).
- `@pytest.mark.integration` — touches a temporary sqlite DB.

### Frontend (`racing-analyzer/__tests__/`)

| Directory | What it covers | Count |
|---|---|---|
| `__tests__/auth/` | Phase 1 — Turnstile widget, AuthContext (CSRF + login result codes), register / verify-email / forgot-password / reset-password pages | 21 |
| `__tests__/phase2/` | UserPrefsService (CSRF header injection, debouncer coalescing with fake timers), raceMath (parse, head-to-head gap, adjusted gap, trend arrows) | 32 |
| `__tests__/utils/` | Existing config helper test | 4 |

Jest config is in `racing-analyzer/jest.config.js` with `next/jest` so
the same module resolution + babel preset Next uses applies.
`jest.setup.js` mocks `window.matchMedia` and `localStorage`.

## Adding a new test

### Backend (integration)

```python
# tests/test_phaseX/test_thing.py
import pytest
from tests.test_auth.conftest import login_as, csrf_token

pytestmark = pytest.mark.integration

def test_X_does_Y(client, authenticated_user):
    login_as(client, authenticated_user["username"], authenticated_user["password"])
    token = csrf_token(client)
    resp = client.post("/api/...", json={...}, headers={"X-CSRF-Token": token})
    assert resp.status_code == 200
    # ... inspect auth.db directly via sqlite3.connect("auth.db") ...
```

Need a `tests/test_phaseX/conftest.py` that re-exports from
`tests/test_auth/conftest.py` so the fixtures resolve:

```python
from tests.test_auth.conftest import (  # noqa: F401
    auth_app, reset_db, client, mock_email,
    authenticated_admin, authenticated_user,
)
```

### Frontend

```typescript
// racing-analyzer/__tests__/<area>/Thing.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

jest.mock('@/utils/config', () => ({
  API_BASE_URL: 'http://api.test',
  TURNSTILE_SITE_KEY: '',   // dev short-circuit
  INVITE_REQUIRED: true,
}));

import Thing from '@/app/.../Thing';

describe('Thing', () => {
  beforeEach(() => { (global.fetch as unknown) = jest.fn(); });

  test('does X', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: () => Promise.resolve({...}) });
    render(<Thing />);
    fireEvent.click(screen.getByRole('button', { name: /label/i }));
    await waitFor(() => expect(/* ... */).toBeTruthy());
  });
});
```

## Coverage

`pytest --cov=. --cov-report=html` generates `htmlcov/index.html`.
Coverage threshold isn't enforced (yet); the goal is meaningful tests
not a number. Auth + prefs paths sit around 85–90%; pure read endpoints
(e.g. `cross-track-sessions`) are tested but not exhaustively because
they hit per-track DBs that aren't present in the test sandbox.

## CI

GitHub Actions (`.github/workflows/tests.yml`) runs:

- `frontend-tests` (Node 20.x, 22.x): `npm ci` + `npm run lint`
  (`continue-on-error`) + `npm test`.
- `backend-tests` (Python 3.11, 3.12): `pip install -r requirements.txt`
  + `pytest --cov=. --cov-report=xml --cov-report=term`.
- `build`: runs after both pass — `npm run build` of the Next app with
  `NEXT_PUBLIC_TURNSTILE_SITE_KEY=""` set so the dev-mode soft-pass
  path is exercised.

Coverage XML is uploaded to Codecov (`fail_ci_if_error: false`).

## What was removed

The pre-Phase-1 test suites (`tests/test_api/`, `tests/test_websocket/`,
`__tests__/components/RaceDashboard/*`, `__tests__/services/WebSocketService.test.ts`)
were deleted on 2026-05-26. They imported APIs that had been removed
(`race_ui.db_pool`) or asserted on UI behavior that Phase 1 + 2
replaced. Restoring them would require rewriting the tests, not just
unblocking them.
