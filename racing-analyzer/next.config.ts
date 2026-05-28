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
};

export default nextConfig;
