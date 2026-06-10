import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't ship `.js.map` files to browsers in production. Default in older
  // Next was off; newer 15.x emits them unless explicitly disabled. Source
  // maps let anyone reconstruct our original TS source from the minified
  // bundle, which defeats the whole point of shipping minified code.
  productionBrowserSourceMaps: false,

  // Run React's strict mode in dev (catches accidental side-effects in
  // useEffect). No production impact.
  reactStrictMode: true,

  // Strip console.* calls from the production bundle, EXCEPT for error/warn
  // which we keep so real-world issues still surface in the user's console.
  // This neutralizes the 40+ debug `console.log`s the audit flagged without
  // requiring per-site NODE_ENV guards everywhere.
  compiler: {
    removeConsole: {
      exclude: ['error', 'warn'],
    },
  },

  // Security headers applied to every response. Defense-in-depth — the
  // backend should set its own, but the Next.js layer gets the static
  // assets + first-paint HTML that the dashboard is served from.
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          // 1 year HSTS, include subdomains, eligible for browser preload list.
          // Tells browsers to ONLY ever load kart.krranalyser.fr over HTTPS,
          // which kills downgrade attacks. Once shipped, this is hard to
          // roll back (browsers cache it for the full year) — but we already
          // serve HTTPS-only in prod, so committing is safe.
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' },
          // Browsers MUST NOT sniff a response's MIME type — only trust the
          // Content-Type header we send. Stops user-uploaded files from
          // executing as JS/HTML.
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          // Refuse to render in an <iframe> on someone else's domain.
          // Defends against clickjacking (a malicious site embedding the
          // dashboard and overlaying invisible UI).
          { key: 'X-Frame-Options', value: 'DENY' },
          // Don't leak the URL path (which may contain a track name, team
          // name, etc.) to third-party links the user clicks.
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          // Disable browser features we never use — saves a fingerprint
          // signal and blocks accidental privilege escalation by a future
          // dependency.
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()' },
          // Permissive CSP that allows what we actually use:
          //   - Cloudflare Turnstile (script + frame for the captcha widget)
          //   - Our backend API + Socket.IO over WSS
          //   - Inline styles (Tailwind/Next inject these)
          //   - data: URIs for the inlined SVG icons we use
          // Tightening this further (e.g. adding script hashes) would break
          // Next's runtime — start permissive, ratchet down after measuring.
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
               `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === 'development' ? " 'unsafe-eval'" : ''} https://challenges.cloudflare.com`,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https:",
              "font-src 'self' data:",
              "connect-src 'self' https://kart.krranalyser.fr wss://kart.krranalyser.fr https://challenges.cloudflare.com",
              "frame-src 'self' https://challenges.cloudflare.com",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join('; '),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
