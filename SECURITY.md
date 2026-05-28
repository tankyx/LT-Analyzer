# Security Policy

## Reporting a Vulnerability

If you discover a security issue in LT-Analyzer (web dashboard, backend API,
or Android companion), please report it **privately** so we can fix it before
it's exploited in the wild.

**Email**: `tanguy.pedrazzoli@gmail.com`
Use a subject line starting with `[SECURITY]`.

Please include:

- A description of the issue and the impact (what an attacker could achieve)
- Steps to reproduce, ideally with a minimal proof-of-concept
- The affected component(s): web frontend, backend Flask API, Android client,
  or the AlphaHub/Apex integration layer
- Whether you've already disclosed this to anyone else, and your preferred
  disclosure timeline

You should receive a first response within **72 hours** and a fix or
mitigation plan within **14 days** for high-severity issues. We don't run
a paid bug-bounty programme but will credit reporters in the release notes
(unless you prefer to stay anonymous).

## Scope

In scope:

- Authentication / session management (`/api/auth/*`, Flask session cookies)
- CSRF and authorization bypasses on any `/api/*` endpoint
- Data exfiltration from the per-track race databases or the auth DB
- XSS / template injection in the Next.js dashboard
- SQL injection in any backend query path (parsers, race_ui, fleet endpoints)
- Privilege escalation (regular user → admin)
- Insecure deserialization of WebSocket frames or Pusher payloads
- Path traversal in admin file/track operations
- Vulnerabilities in the Android companion's auth flow or session handling

Out of scope (not vulnerabilities for this project):

- Rate limiting on public read-only endpoints
- Self-XSS that requires the victim to paste attacker content into their own console
- Social-engineering of users or operators
- Physical access to the server
- DoS via volume against unauthenticated endpoints
- Issues in third-party services we depend on (Apex Timing, AlphaHub,
  Cloudflare Turnstile) — report those upstream

## Hardening Already in Place

For context when triaging reports, here's what's already implemented:

- Session cookies marked `HttpOnly`, `Secure`, `SameSite=Lax`
  (Flask session defaults, not overridable from JS)
- CSRF token (preflight `/api/auth/csrf` → `X-CSRF-Token` on every unsafe verb)
- `bcrypt` password hashing
- Per-account login attempt throttling
- Email verification required before login
- Admin role enforced server-side on every `/api/admin/*` endpoint
  (the client-side check in `useAuth()` is defense-in-depth only)
- Backend audit log (`_audit()`) for state-changing admin operations
- Frontend ships with Content-Security-Policy, HSTS, X-Frame-Options=DENY,
  X-Content-Type-Options=nosniff, Permissions-Policy, Referrer-Policy
  (see `racing-analyzer/next.config.ts`)
- No browser source maps in production
- `console.log/info/debug` stripped from the production bundle at build time
- Android client uses cert-pinned HTTPS + session cookies; no plaintext
  credentials persisted

## Disclosure

Once a fix is shipped, we'll:

1. Publish a release with the fix (`git tag` + GitHub release notes)
2. Credit you in the release notes if you'd like
3. Update this file with any general lessons that other deployments
   should know about

We'd appreciate a coordinated disclosure window of at least 14 days from
report to public details.

## License Note

LT-Analyzer is licensed under the Business Source License 1.1
(see [LICENSE](./LICENSE)). Security research is permitted under the
"non-production use" clause — you don't need to buy a commercial license
to find or report bugs.
